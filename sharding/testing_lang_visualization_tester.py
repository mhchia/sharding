import graphviz as gv

from ethereum import utils

from sharding import testing_lang
from sharding.tools import tester

tl = testing_lang.TestingLang()
cmds = """
    D0
    W0
    D0
    B25
    C0
    R0
    R0
    B5
    RC0
    C0
    R0
    B5
    RC1
    C0,0,0
    B5
    RC2
    C0,1,0
    R0
    B5
    C0,1,1
    B5
    C0
    B5
    C1
    B5
    RC3
    C0,2,1
"""
cmd = """
    D0
    B25
    C0
    B5
    R0
    R0
    B1
    RC0
    RC1
    C0
    B1
"""
tl.execute(cmds)

expected_period_number = tl.c.chain.get_expected_period_number()

g = gv.Digraph('G', filename='image')
# g.attr(splines='polyline')
# g.attr(nodesep='2')
# g.attr(ranksep='2.0')

NUM_TX_IN_BLOCK = 3
EMPTY_TX = '&nbsp;' * 4
GENESIS_HASH = b'\x00' * 32

record = tl.record


def draw_event_edge(g, node, prev_node):
    g.edge(node, prev_node, style='dashed', constraint='false')


def draw_struct(g, prev_hash, current_hash, height, txs, struct_type='block'):
    assert len(txs) <= NUM_TX_IN_BLOCK
    assert isinstance(height, int)
    hash_label = '<hash> {} {}:\n {}'.format(struct_type, height, current_hash)
    prev_label = '<prev> prev: \n {}'.format(prev_hash)
    txs_label = '{'
    for i in range(NUM_TX_IN_BLOCK):
        if i >= len(txs):
            txs_label += '<tx{}> '.format(i)
            txs_label += EMPTY_TX
        else:
            txs_label += '<{}> '.format(txs[i])
            txs_label += txs[i]
        if i != NUM_TX_IN_BLOCK - 1:
            txs_label += ' | '
    txs_label += '}'
    # label = '{ %s | %s | %s }' % (hash_label, txs_label, prev_label)
    if len(txs) != 0:
        label = '{ %s | %s }' % (hash_label, txs_label)
    else:
        label = '{ %s }' % hash_label
    shape = 'Mrecord' if struct_type == 'collation' else 'record'
    g.node(current_hash, label, shape=shape)
    g.edge(current_hash, prev_hash) # , weight=weight)

    # draw event edges
    for label in txs:
        label_index = current_hash + ':' + label
        try:
            prev_label_index = record.node_label_map[label_index]
            draw_event_edge(g, label_index, prev_label_index)
        except:
            pass


# draw period
layers = {}
mainchain_caption = "mainchain"
chain = tl.get_tester_chain().chain
current_block = chain.head
min_hash = testing_lang.get_shorten_hash(current_block.header.hash)

g.node(mainchain_caption, shape='none')
layers[mainchain_caption] = []
# for i in range(expected_period_number + 1):
#     name = str(i)
#     g.edge(name, prev)
#     g.node(name, label=name, shape='box')
#     layers[name] = []
#     prev = name

def draw_block(block):
    # prev_block_hash
    pass

while current_block is not None:
    # draw head
    prev_block = chain.get_parent(current_block)
    if prev_block is None:
        prev_block_hash = mainchain_caption
    else:
        prev_block_hash = testing_lang.get_shorten_hash(prev_block.header.hash)
    current_block_hash = testing_lang.get_shorten_hash(current_block.header.hash)
    # print("!@# {}: {}".format(current_block.header.number, current_block_hash))
    tx_labels = record.get_tx_labels_from_node(current_block.header.hash)
    draw_struct(
        g,
        prev_block_hash,
        current_block_hash,
        current_block.header.number,
        tx_labels,
    )
    layers[current_block_hash] = []
    current_block = prev_block


# draw collations per shard

# for shard_id, collation_map in tl.collation_map.items():
for shard_id, collations in record.collations.items():
    shardchain_caption = "shard_" + str(shard_id)
    g.node(shardchain_caption, shape='none')
    layers[mainchain_caption].append(shardchain_caption)
    for collation_hash, collation in collations.items():
        if testing_lang.get_collation_hash(collation) == GENESIS_HASH:
            continue
        # label = "C{},{},{}\n\n".format(shard_id, i, j)
        label = ''
        i = collation.header.number
        name = testing_lang.get_shorten_hash(collation.header.hash)
        label += name
        prev_name = collation.header.parent_collation_hash
        if prev_name == GENESIS_HASH:
            prev_name = shardchain_caption
        else:
            prev_name = testing_lang.get_shorten_hash(prev_name)
        period_start_prevhash = testing_lang.get_shorten_hash(
            collation.header.period_start_prevhash,
        )
        layers[period_start_prevhash].append(name)
        # g.edge(name, prev_name)
        # g.node(name, label=label)#, shape='Mrecord')
        tx_labels = record.get_tx_labels_from_node(collation.header.hash)
        draw_struct(g, prev_name, name, i, tx_labels, struct_type='collation')

def add_rank(g, node_list, rank='same'):
    rank_same_str = "\t{rank=%s; " % rank
    for node in node_list:
        rank_same_str += (g._quote(node) + '; ')
    rank_same_str += '}'
    g.body.append(rank_same_str)

# set rank
for period, labels in layers.items():
    rank = 'same'
    if period == min_hash:
        rank = 'source'
    elif period == mainchain_caption:
        rank = 'max'
    add_rank(g, [period] + labels, rank)

print(g.source)
print("len(made_txs): ", len(record.made_txs))
g.view()
