import time
import json
import logging
from collections import defaultdict
import rlp

from ethereum.exceptions import (
    InvalidTransaction,
    VerificationFailed,
)
from ethereum.slogging import get_logger
from ethereum.config import Env
from ethereum.state import State
from ethereum.pow.consensus import initialize
from ethereum.utils import (
    encode_hex,
    decode_hex,
)

from sharding.collation import (
    CollationHeader,
    Collation,
)
from sharding.collator import apply_collation
from sharding.state_transition import update_collation_env_variables

log = get_logger('sharding.shard_chain')
log.setLevel(logging.DEBUG)


def initialize_genesis_keys(state, genesis, shard_id):
    """Rewrite ethereum.genesis_helpers.initialize_genesis_keys
    """
    db = state.db
    prefix = 'SHARD_' + str(shard_id) + '_'
    # db.put('GENESIS_NUMBER', str(genesis.header.number))
    db.put(prefix + 'GENESIS_HASH', str(genesis.header.hash))
    db.put(prefix + 'GENESIS_STATE', json.dumps(state.to_snapshot()))
    db.put(prefix + 'GENESIS_RLP', rlp.encode(genesis))
    db.put(b'score:' + genesis.header.hash, "0")
    db.put(b'state:' + genesis.header.hash, state.trie.root_hash)
    db.put(genesis.header.hash, 'GENESIS')
    db.commit()


def set_processing_collation(func):
    def new_func(self, collation, period_start_prevblock):
        self.processing_collation = collation
        result = func(self, collation, period_start_prevblock)
        self.processing_collation = None
        return result
    return new_func


class ShardChain(object):
    def __init__(self, shard_id, env=None,
                 new_head_cb=None, reset_genesis=False, localtime=None, max_history=1000,
                 initial_state=None, main_chain=None, **kwargs):
        self.env = env or Env()
        self.shard_id = shard_id
        self.active = False
        self.is_syncing = True

        self.collation_blockhash_lists = defaultdict(list)    # M1: collation_header_hash -> list[blockhash]
        self.head_collation_of_block = {}   # M2: blockhash -> head_collation
        self.main_chain = main_chain
        self.invalid_collation_listeners = []
        self.processing_collation = None

        # Initialize the state
        head_hash_key = 'shard_' + str(shard_id) + '_head_hash'
        if head_hash_key in self.db:  # new head tag
            self.state = self.mk_poststate_of_collation_hash(self.db.get(head_hash_key))
            log.info(
                'Initializing shard chain from saved head, #%d (%s)' %
                (self.state.prev_headers[0].number, encode_hex(self.state.prev_headers[0].hash)))
            self.head_hash = self.state.prev_headers[0].hash
        else:
            # no head_hash in db -> empty shard chain
            if initial_state is not None and isinstance(initial_state, State):
                # Normally, initial_state is for testing
                assert env is None
                self.state = initial_state
                self.env = self.state.env
                log.info('Initializing chain from provided state')
            else:
                self.state = State(env=self.env)
                self.last_state = self.state.to_snapshot()

            self.head_hash = self.env.config['GENESIS_PREVHASH']
            self.db.put(self.head_hash, 'GENESIS')
            self.db.put(head_hash_key, self.head_hash)

            # initial score
            key = b'score:' + self.head_hash
            self.db.put(key, str(0))
            self.db.commit()
            reset_genesis = True

        assert self.env.db == self.state.db

        initialize(self.state)
        self.new_head_cb = new_head_cb

        if reset_genesis:
            initialize_genesis_keys(self.state, Collation(CollationHeader()), self.shard_id)

        self.time_queue = []
        self.parent_queue = {}
        self.localtime = time.time() if localtime is None else localtime
        self.max_history = max_history

    @property
    def db(self):
        return self.env.db

    @property
    def head(self):
        """head collation
        """
        try:
            collation_rlp = self.db.get(self.head_hash)
            # [TODO] no genesis collation
            if collation_rlp == 'GENESIS':
                return Collation(CollationHeader())
                # return self.genesis
            else:
                return rlp.decode(collation_rlp, Collation)
            return rlp.decode(collation_rlp, Collation)
        except Exception as e:
            log.info(str(e))
            return None

    @set_processing_collation
    def add_collation(self, collation, period_start_prevblock):
        """Add collation to db and update score
        """
        if collation.header.parent_collation_hash in self.env.db:
            log.info(
                'Receiving collation(%s) which its parent is in db: %s' %
                (encode_hex(collation.header.hash), encode_hex(collation.header.parent_collation_hash)))
            if self.is_first_collation(collation):
                log.debug('It is the first collation of shard {}'.format(self.shard_id))
            temp_state = self.mk_poststate_of_collation_hash(collation.header.parent_collation_hash)
            try:
                apply_collation(
                    temp_state, collation, period_start_prevblock,
                    None if self.main_chain is None else self.main_chain.state,
                    self.shard_id
                )
            except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:
                self.call_listeners(collation=collation)
                log.info('Collation %s with parent %s invalid, reason: %s' %
                         (encode_hex(collation.header.hash), encode_hex(collation.header.parent_collation_hash), str(e)))
                return False
            deletes = temp_state.deletes
            changed = temp_state.changed
            collation_score = self.get_score(collation)
            log.info('collation_score of {} is {}'.format(encode_hex(collation.header.hash), collation_score))
        # Collation has no parent yet
        else:
            changed = []
            deletes = []
            log.info(
                'Receiving collation(%s) which its parent is NOT in db: %s' %
                (encode_hex(collation.header.hash), encode_hex(collation.header.parent_collation_hash)))
            if collation.header.parent_collation_hash not in self.parent_queue:
                self.parent_queue[collation.header.parent_collation_hash] = []
            self.parent_queue[collation.header.parent_collation_hash].append(collation)
            log.info('No parent found. Delaying for now')
            return False
        self.db.put(collation.header.hash, rlp.encode(collation))

        self.db.put(b'changed:'+collation.hash, b''.join(list(changed.keys())))
        # log.debug('Saved %d address change logs' % len(changed.keys()))
        self.db.put(b'deletes:'+collation.hash, b''.join(deletes))
        # log.debug('Saved %d trie node deletes for collation (%s)' % (len(deletes), encode_hex(collation.hash)))

        # TODO: Delete old junk data
        # deletes, changed

        self.db.commit()
        log.info(
            'Added collation (%s) with %d txs' %
            (encode_hex(collation.header.hash)[:8],
                len(collation.transactions)))

        # Call optional callback
        if self.new_head_cb and self.is_first_collation(collation):
            self.new_head_cb(collation)

        # TODO: It seems weird to use callback function to access member of MainChain
        try:
            self.main_chain.handle_ignored_collation(collation)
        except Exception as e:
            log.info('handle_ignored_collation exception: {}'.format(str(e)))
            return False
        try:
            self.main_chain.update_head_collation_of_block(collation)
        except Exception as e:
            log.info('update_head_collation_of_block exception: {}'.format(str(e)))
            return False

        return True

    def mk_poststate_of_collation_hash(self, collation_hash):
        """Return the post-state of the collation
        """
        if collation_hash not in self.db:
            raise Exception("Collation hash %s not found" % encode_hex(collation_hash))

        collation_rlp = self.db.get(collation_hash)
        if collation_rlp == 'GENESIS':
            return State.from_snapshot(json.loads(self.db.get('SHARD_' + str(self.shard_id) + '_GENESIS_STATE')), self.env)
        collation = rlp.decode(collation_rlp, Collation)

        state = State(env=self.env)
        state.trie.root_hash = collation.header.post_state_root

        update_collation_env_variables(state, collation)
        state.gas_used = 0
        state.txindex = len(collation.transactions)
        state.recent_uncles = {}
        state.prev_headers = []
        state.log_listeners = self.state.log_listeners

        assert len(state.journal) == 0, state.journal
        return state

    def get_parent(self, collation):
        """Get the parent collation of a given collation
        """
        if self.is_first_collation(collation):
            return None
        return self.get_collation(collation.header.parent_collation_hash)

    def get_collation(self, collation_hash):
        """Get the collation with a given collation hash
        """
        try:
            collation_rlp = self.db.get(collation_hash)
            if collation_rlp == 'GENESIS':
                return Collation(CollationHeader())
                # if not hasattr(self, 'genesis'):
                #     self.genesis = rlp.decode(self.db.get('GENESIS_RLP'), sedes=Block)
                # return self.genesis
            else:
                return rlp.decode(collation_rlp, Collation)
        except Exception as e:
            log.debug("Failed to get collation", hash=encode_hex(collation_hash), error=str(e))
            return None

    def get_score(self, collation):
        """Get the score of a given collation
        """
        score = 0

        if not collation:
            return 0
        key = b'score:' + collation.header.hash

        fills = []

        while key not in self.db and collation is not None:
            fills.insert(0, collation.header.hash)
            key = b'score:' + collation.header.parent_collation_hash
            collation = self.get_parent(collation)

        score = int(self.db.get(key))
        log.debug('int(self.db.get(key)):{}'.format(int(self.db.get(key))))

        for h in fills:
            key = b'score:' + h
            score += 1
            self.db.put(key, str(score))

        return score

    def get_head_coll_score(self, blockhash):
        if blockhash in self.head_collation_of_block:
            prev_head_coll_hash = self.head_collation_of_block[blockhash]
            prev_head_coll = self.get_collation(prev_head_coll_hash)
            prev_head_coll_score = self.get_score(prev_head_coll)
        else:
            prev_head_coll_score = 0
        return prev_head_coll_score

    def is_first_collation(self, collation):
        """Check if the given collation is the first collation of this shard
        """
        return collation.header.parent_collation_hash == self.env.config['GENESIS_PREVHASH']

    def activate(self):
        self.active = True

    def deactivate(self):
        self.active = False

    def sync(self, state_data, collation, score, collation_blockhash_lists, head_collation_of_block):
        self.state = State.from_snapshot(state_data, self.env, executing_on_head=True)
        """ A lazy sync for simulation
        """
        self.head_hash = collation.hash
        self.db.put(collation.header.hash, rlp.encode(collation))
        self.db.put(b'score:' + collation.header.hash, score)
        # self.collation_blockhash_lists = self.collation_blockhash_lists_from_dict(collation_blockhash_lists)
        for collhash, b_list in collation_blockhash_lists.items():
            if collhash not in collation_blockhash_lists:
                self.collation_blockhash_lists[collhash] = []
            self.collation_blockhash_lists[collhash].extend(b_list)
            self.collation_blockhash_lists[collhash] = list(set(self.collation_blockhash_lists[collhash]))
        # self.head_collation_of_block = self.head_collation_of_block_from_dict(head_collation_of_block)
        for blockhash, collhash in head_collation_of_block.items():
            self.head_collation_of_block[blockhash] = collhash

    def collation_blockhash_lists_to_dict(self):
        output = {}
        for collhash, b_list in self.collation_blockhash_lists.items():
            output[encode_hex(collhash)] = [encode_hex(b) for b in b_list]
        return output

    def head_collation_of_block_to_dict(self):
        output = {}
        for blockhash, collhash in self.head_collation_of_block.items():
            output[encode_hex(blockhash)] = encode_hex(collhash)
        return output

    def collation_blockhash_lists_from_dict(self, collation_blockhash_lists):
        output = {}
        for collhash, b_list in collation_blockhash_lists.items():
            output[decode_hex(collhash)] = [decode_hex(b) for b in b_list]
        return output

    def head_collation_of_block_from_dict(self, head_collation_of_block):
        output = {}
        for blockhash, collhash in head_collation_of_block.items():
            output[decode_hex(blockhash)] = decode_hex(collhash)
        return output

    def call_listeners(self, *args, **kwargs):
        for func in self.invalid_collation_listeners:
            func(*args, **kwargs)
