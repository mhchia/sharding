from ethereum import utils
from ethereum.tools import tester as t
import rlp
from solc import compile_source
from viper import compiler
from web3 import Web3, HTTPProvider, TestRPCProvider
from web3.contract import ConciseContract

from sharding import validator_manager_utils


# web3 = Web3(IPCProvider())
# web3 = Web3(TestRPCProvider())


class RPCHandler:

    RPC_SERVER_URL = 'http://localhost:8545'

    def __init__(self):
        self.set_attributes()
        self.setup_contract_instance()


    def set_attributes(self):
        self._vmc_addr = utils.checksum_encode(validator_manager_utils.get_valmgr_addr())
        self._vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
        self._vmc_code = validator_manager_utils.get_valmgr_code()
        self._vmc_abi = compiler.mk_full_signature(self._vmc_code)
        self._vmc_ct = validator_manager_utils.get_valmgr_ct()


    def is_vmc_deployed(self):
        return self._w3.eth.getCode(self._vmc_addr) != b''


    def deploy_vmc(self):
        vmc_tx = validator_manager_utils.get_valmgr_tx()
        raw_vmc_tx = rlp.encode(vmc_tx)
        raw_vmc_tx_hex = self._w3.toHex(raw_vmc_tx)
        try:
            result = self._w3.eth.sendRawTransaction(raw_vmc_tx_hex)
            print('!@# result:', result)
        except ValueError as e:
            print(e)
            pass


    def setup_contract_instance(self):
        self._w3 = Web3(HTTPProvider(self.RPC_SERVER_URL))
        if not self.is_vmc_deployed():
            self.deploy_vmc()
        self._vmc = self._w3.eth.contract(
            self._vmc_addr,
            abi=self._vmc_abi,
            bytecode=self._vmc_bytecode,
        )


    def sample(self, shard_id):
        return self._vmc.call().sample(shard_id)


def print_current_contract_address(sender_address):
    list_addresses = [
        utils.checksum_encode(utils.mk_contract_address(t.a0, i)) for i in range(nonce + 1)
    ]
    print(list_addresses)


def main():
    rpc = RPCHandler()


if __name__ == '__main__':
    main()
