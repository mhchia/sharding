import json

from ethereum import utils
from ethereum.tools import tester as t
import rlp
from web3 import Web3, HTTPProvider, TestRPCProvider
from web3.contract import ConciseContract
from viper import compiler

from sharding import validator_manager_utils

w3 = Web3(HTTPProvider('http://localhost:8545'))
# web3 = Web3(IPCProvider())
# web3 = Web3(TestRPCProvider())

vmc_addr = utils.checksum_encode(validator_manager_utils.get_valmgr_addr())
vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
vmc_code = validator_manager_utils.get_valmgr_code()
vmc_interface = compiler.mk_full_signature(vmc_code)
vmc_ct = validator_manager_utils.get_valmgr_ct()
print(vmc_interface)
# print(bytecode)



# print(w3.personal.listAccounts)

# for key in t.keys:
#     try:
#         w3.personal.importRawKey(key, '123')
#     except ValueError:
#         pass

# result = w3.personal.unlockAccount(utils.checksum_encode(t.a0), '123')
# print(result)

vmc_tx = validator_manager_utils.get_valmgr_tx()
raw_vmc_tx = rlp.encode(vmc_tx)
raw_vmc_tx_hex = w3.toHex(raw_vmc_tx)
try:
    w3.eth.sendRawTransaction(raw_vmc_tx_hex)
except ValueError:
    pass

# ContractFactory = w3.eth.contract(abi=json.dumps(vmc_interface))
# ContractFactory = w3.eth.contract(abi=vmc_interface)
# vmc = ContractFactory(vmc_addr)
# result = vmc.call().sample(0)

vmc = w3.eth.contract(vmc_addr, abi=vmc_interface, ContractFactoryClass=ConciseContract)
result = vmc.call().sample(0)
print(result)

# print(utils.checksum_encode(validator_manager_utils.get_valmgr_sender_addr()))


# w3.eth.start(1)
# print(len(t.k0))
