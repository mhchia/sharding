from sharding.config import sharding_config

# FIXME: should be 25, fix it, only for faster testing
SHUFFLING_CYCLE_LENGTH = sharding_config['SHUFFLING_CYCLE_LENGTH'] = 5
DEPOSIT_SIZE = sharding_config['DEPOSIT_SIZE']
PERIOD_LENGTH = sharding_config['PERIOD_LENGTH']

TX_GAS = 510000
GASPRICE = 1
PASSPHRASE = '123'
DEFAULT_RPC_SERVER_URL = 'http://localhost:8545'
