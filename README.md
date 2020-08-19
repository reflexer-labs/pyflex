# pyflex

Python API for Maker contracts.

[![Build Status](https://travis-ci.org/reflexer-labs/pyflex.svg?branch=master)](https://travis-ci.org/reflexer-labs/pyflex)
[![codecov](https://codecov.io/gh/reflexer-labs/pyflex/branch/master/graph/badge.svg)](https://codecov.io/gh/reflexer-labs/pyflex)

<https://chat.reflexer-labs.com/channel/keeper>

## Introduction

The _Generalized Ethereum Bonds_  system incentivizes external agents, called _keepers_,
to automate certain operations around the Ethereum blockchain. In order to ease their
development, an API around most of the Reflexer contracts has been created. It can be used
not only by keepers, but may also be found useful by authors of some other, unrelated
utilities aiming to interact with these contracts.

Based on this API, a set of reference Reflexer keepers is being developed. They all used to reside
in this repository, but now each of them has an individual one: 
[bite-keeper](https://github.com/reflexer-labs/bite-keeper) (SCD only),
[arbitrage-keeper](https://github.com/reflexer-labs/arbitrage-keeper),
[auction-keeper](https://github.com/reflexer-labs/auction-keeper) (MCD only),
[cdp-keeper](https://github.com/reflexer-labs/cdp-keeper) (SCD only),
[market-maker-keeper](https://github.com/reflexer-labs/market-maker-keeper).

You only need to install this project directly if you want to build your own keepers,
or if you want to play with this API library itself. If you just want to install
one of reference keepers, go to one of the repositories linked above and start from there.
Each of these keepers references some version of `pyflex` via a Git submodule.

## Installation

This project uses *Python 3.6.6*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/reflexer-labs/pyflex.git
cd pyflex
pip3 install -r requirements.txt
```

### Known Ubuntu issues

In order for the `secp256k` Python dependency to compile properly, following packages will need to be installed:
```
sudo apt-get install build-essential automake libtool pkg-config libffi-dev python-dev python-pip libsecp256k1-dev
```

(for Ubuntu 18.04 Server)

### Known macOS issues

In order for the Python requirements to install correctly on _macOS_, please install
`openssl`, `libtool`, `pkg-config` and `automake` using [Homebrew](https://brew.sh/):
```
brew install openssl libtool pkg-config automake
```

and set the `LDFLAGS` environment variable before you run `pip3 install -r requirements.txt`:
```
export LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" 
```

## Available APIs
TODO: Update

The current version provides APIs around:
* `ERC20Token`,
* `Tub`, `Tap`,`Top` and `Vox` (<https://github.com/reflexer-labs/sai>),
* `Vat`, `Cat`, `Vow`, `Jug`, `Flipper`, `Flapper`, `Flopper` (<https://github.com/reflexer-labs/dss>)
* `SimpleMarket`, `ExpiringMarket` and `MatchingMarket` (<https://github.com/reflexer-labs/maker-otc>),
* `TxManager` (<https://github.com/reflexer-labs/tx-manager>),
* `DSGuard` (<https://github.com/dapphub/ds-guard>),
* `DSToken` (<https://github.com/dapphub/ds-token>),
* `DSEthToken` (<https://github.com/dapphub/ds-eth-token>),
* `DSValue` (<https://github.com/dapphub/ds-value>),
* `DSVault` (<https://github.com/dapphub/ds-vault>),
* `EtherDelta` (<https://github.com/etherdelta/etherdelta.github.io>),
* `0x v1` (<https://etherscan.io/address/0x12459c951127e0c374ff9105dda097662a027093#code>, <https://github.com/0xProject/standard-relayer-api>),
* `0x v2`.

APIs around the following functionality have not been implemented:
* Dai Savings Rate (`Pot`)
* Global Settlement (`End`)
* Governance (`DSAuth`, `DSChief`, `DSGuard`, `DSSpell`, `Mom`)

Contributions from the community are appreciated.

## Code samples

Below you can find some code snippets demonstrating how the API can be used both for developing
your own keepers and for creating some other utilities interacting with the _DAI Stablecoin_
ecosystem contracts.

### Token transfer
TODO: Update

This snippet demonstrates how to transfer some SAI from our default address. The SAI token address
is discovered by querying the `Tub`, so all we need as a `Tub` address:

```python
from web3 import HTTPProvider, Web3

from pyflex import Address
from pyflex.token import ERC20Token
from pyflex.numeric import Wad
from pyflex.sai import Tub


web3 = Web3(HTTPProvider(endpoint_uri="http://localhost:8545"))

tub = Tub(web3=web3, address=Address('0xb7ae5ccabd002b5eebafe6a8fad5499394f67980'))
sai = ERC20Token(web3=web3, address=tub.sai())

sai.transfer(address=Address('0x0000000000111111111100000000001111111111'),
             value=Wad.from_number(10)).transact()
``` 

### Updating a DSValue

This snippet demonstrates how to update a `DSValue` with the ETH/USD rate pulled from _CryptoCompare_: 

```python
import json
import urllib.request

from web3 import HTTPProvider, Web3

from pyflex import Address
from pyflex.feed import DSValue
from pyflex.numeric import Wad


def cryptocompare_rate() -> Wad:
    with urllib.request.urlopen("https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD") as url:
        data = json.loads(url.read().decode())
        return Wad.from_number(data['USD'])


web3 = Web3(HTTPProvider(endpoint_uri="http://localhost:8545"))

dsvalue = DSValue(web3=web3, address=Address('0x038b3d8288df582d57db9be2106a27be796b0daf'))
dsvalue.update_result(cryptocompare_rate().value).transact()
```
### System Coin

This snippet demonstrates how to create a CDP and draw system coin

```python
import sys
from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad


web3 = Web3(HTTPProvider(endpoint_uri="https://localhost:8545",
                         request_kwargs={"timeout": 10}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass

geb = GfDeployment.from_json(web3=web3, conf=open("tests/config/kovan-addresses.json", "r").read())
our_address = Address(web3.eth.defaultAccount)

# Choose the desired collateral; in this case we'll wrap some Eth
collateral = geb.collaterals['ETH-A']
collateral_type = collateral.collateral_type
collateral.collateral.deposit(Wad.from_number(3)).transact()

# Add collateral and allocate the desired amount of system coin
collateral.approve(our_address)
collateral.adapter.join(our_address, Wad.from_number(3)).transact()
geb.cdp_engine.modify_cdp_collateralization(ilk, our_address, delta_collateral=Wad.from_number(3), delta_debt=Wad.from_number(153)).transact()
print(f"CDP system coin balance before withdrawal: {geb.cdp_engine.coin_balance(our_address)}")

# Mint and withdraw our system coin
geb.approve_system_coin(our_address)
geb.system_coin_adapter.exit(our_address, Wad.from_number(153)).transact()
print(f"CDP system coin balance after withdrawal:  {geb.cdp_engine.coin_balance(our_address)}")

# Repay (and burn) our system coin
assert geb.system_coin_adapter.join(our_address, Wad.from_number(153)).transact()
print(f"CDP system balance after repayment:   {geb.cdp_engine.coin_balance(our_address)}")

# Withdraw our collateral
geb.cdp_engine.modify_cdp_collateralization(ilk, our_address, delta_collateral=Wad(0), delta_debt=Wad.from_number(-153)).transact()
geb.cdp_engine.modify_cdp_collateralization(ilk, our_address, delta_collateral=Wad.from_number(-3), delta_debt=Wad(0)).transact()
collateral.adapter.exit(our_address, Wad.from_number(3)).transact()
print(f"CDP system coin balance w/o collateral:    {geb.cdp_engine.coin_balance(our_address)}")
```

### Asynchronous invocation of Ethereum transactions
TODO: Update

This snippet demonstrates how multiple token transfers can be executed asynchronously:

```python
from web3 import HTTPProvider
from web3 import Web3

from pyflex import Address, synchronize
from pyflex.numeric import Wad
from pyflex.sai import Tub
from pyflex.token import ERC20Token


web3 = Web3(HTTPProvider(endpoint_uri="http://localhost:8545"))

tub = Tub(web3=web3, address=Address('0x448a5065aebb8e423f0896e6c5d525c040f59af3'))
sai = ERC20Token(web3=web3, address=tub.sai())
skr = ERC20Token(web3=web3, address=tub.skr())

synchronize([sai.transfer(Address('0x0101010101020202020203030303030404040404'), Wad.from_number(1.5)).transact_async(),
             skr.transfer(Address('0x0303030303040404040405050505050606060606'), Wad.from_number(2.5)).transact_async()])
```

### Multiple invocations in one Ethereum transaction
TODO: Update

This snippet demonstrates how multiple token transfers can be executed in one Ethereum transaction.
A `TxManager` instance has to be deployed and owned by the caller.

```python
from web3 import HTTPProvider
from web3 import Web3

from pyflex import Address
from pyflex.approval import directly
from pyflex.numeric import Wad
from pyflex.sai import Tub
from pyflex.token import ERC20Token
from pyflex.transactional import TxManager


web3 = Web3(HTTPProvider(endpoint_uri="http://localhost:8545"))

tub = Tub(web3=web3, address=Address('0x448a5065aebb8e423f0896e6c5d525c040f59af3'))
sai = ERC20Token(web3=web3, address=tub.sai())
skr = ERC20Token(web3=web3, address=tub.skr())

tx = TxManager(web3=web3, address=Address('0x57bFE16ae8fcDbD46eDa9786B2eC1067cd7A8f48'))
tx.approve([sai, skr], directly())

tx.execute([sai.address, skr.address],
           [sai.transfer(Address('0x0101010101020202020203030303030404040404'), Wad.from_number(1.5)).invocation(),
            skr.transfer(Address('0x0303030303040404040405050505050606060606'), Wad.from_number(2.5)).invocation()]).transact()
```

### Ad-hoc increasing of gas price for asynchronous transactions
TODO: Update

```python
import asyncio
from random import randint

from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.gas import FixedGasPrice
from pyflex.oasis import SimpleMarket


web3 = Web3(HTTPProvider(endpoint_uri=f"http://localhost:8545"))
otc = SimpleMarket(web3=web3, address=Address('0x375d52588c3f39ee7710290237a95C691d8432E7'))


async def bump_with_increasing_gas_price(order_id):
    gas_price = FixedGasPrice(gas_price=1000000000)
    task = asyncio.ensure_future(otc.bump(order_id).transact_async(gas_price=gas_price))

    while not task.done():
        await asyncio.sleep(1)
        gas_price.update_gas_price(gas_price.gas_price + randint(0, gas_price.gas_price))

    return task.result()


bump_task = asyncio.ensure_future(bump_with_increasing_gas_price(otc.get_orders()[-1].order_id))
event_loop = asyncio.get_event_loop()
bump_result = event_loop.run_until_complete(bump_task)

print(bump_result)
print(bump_result.transaction_hash)
```

## Testing

Prerequisites:
* [docker and docker-compose](https://www.docker.com/get-started)

This project uses [pytest](https://docs.pytest.org/en/latest/) for unit testing.  Testing of GEB is 
performed on a Dockerized local testchain included in `tests\config`.

In order to be able to run tests, please install development dependencies first by executing:
```
pip3 install -r requirements-dev.txt
```

You can then run all tests with:
```
./test.sh
```

By default, `pyflex` will not send a transaction to the chain if gas estimation fails, because this means the 
transaction would revert.  For testing purposes, it is sometimes useful to send bad transactions to the chain.  To 
accomplish this, set class variable `gas_estimate_for_bad_txs` in your application.  For example:
```
from pyflex import Transact
Transact.gas_estimate_for_bad_txs = 200000
```

## License

See [COPYING](https://github.com/reflexer-labs/pyflex/blob/master/COPYING) file.
