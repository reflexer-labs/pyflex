# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2017-2018 reverendus, bargst
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import os
import re
from typing import Dict, List, Optional

import pkg_resources
#from pyflex.auctions import Flapper, Flopper, Flipper
from pyflex.auctions import SurplusAuctionHouse, DebtAuctionHouse, CollateralAuctionHouse
from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.approval import directly, approve_cdp_modification_directly
from pyflex.auth import DSGuard
from pyflex.etherdelta import EtherDelta
#from pyflex.dss import Cat, Collateral, DaiJoin, GemJoin, GemJoin5, Ilk, Jug, Pot, Spotter, Vat, Vow
# removed CollateralJoin5
from pyflex.gf import LiquidationEngine, Collateral, CoinJoin, CollateralJoin, CollateralType, TaxCollector, CoinSavingsAccount, OracleRelayer, CDPEngine, AccountingEngine
from pyflex.proxy import ProxyRegistry, GebProxyActions
from pyflex.feed import DSValue
from pyflex.gas import DefaultGasPrice
from pyflex.governance import DSPause, DSChief
from pyflex.numeric import Wad, Ray
from pyflex.oasis import MatchingMarket
from pyflex.oracles import OSM
from pyflex.sai import Tub, Tap, Top, Vox
from pyflex.shutdown import ShutdownModule, End
from pyflex.token import DSToken, DSEthToken
from pyflex.vault import DSVault
from pyflex.cdpmanager import CdpManager
#from pyflex.dsrmanager import DsrManager


def deploy_contract(web3: Web3, contract_name: str, args: Optional[list] = None) -> Address:
    """Deploys a new contract.

    Args:
        web3: An instance of `Web` from `web3.py`.
        contract_name: Name of the contract, used to find the `abi` and `bin` files.
        args: Optional list of contract constructor parameters.

    Returns:
        Ethereum address of the newly deployed contract, as a :py:class:`pyflex.Address` instance.
    """
    assert(isinstance(web3, Web3))
    assert(isinstance(contract_name, str))
    assert(isinstance(args, list) or (args is None))

    abi = json.loads(pkg_resources.resource_string('pyflex.deployment', f'abi/{contract_name}.abi'))
    bytecode = str(pkg_resources.resource_string('pyflex.deployment', f'abi/{contract_name}.bin'), 'utf-8')
    if args is not None:
        tx_hash = web3.eth.contract(abi=abi, bytecode=bytecode).constructor(*args).transact()
    else:
        tx_hash = web3.eth.contract(abi=abi, bytecode=bytecode).constructor().transact()
    receipt = web3.eth.getTransactionReceipt(tx_hash)
    return Address(receipt['contractAddress'])

class GfDeployment:
    """Represents a GEB Framework deployment.

    Static method `from_json()` should be used to instantiate all the objet of
    a deployment from a json description of all the system addresses.
    """

    NETWORKS = {
        "1": "mainnet",
        "42": "kovan"
    }

    class Config:
        def __init__(self, pause: DSPause, cdp_engine: CDPEngine, acct_engine: AccountingEngine, tax_collector: TaxCollector,
                     liquidation_engine: LiquidationEngine, surplus_auction_house: DebtAuctionHouse,
                     debt_auction_house: DebtAuctionHouse, coin_savings_acct: CoinSavingsAccount, dai: DSToken, coin_join: CoinJoin,
                     gov: DSToken, oracle_relayer: OracleRelayer, ds_chief: DSChief, esm: ShutdownModule, end: End,
                     proxy_registry: ProxyRegistry, proxy_actions: GebProxyActions, cdp_manager: CdpManager,
                     collaterals: Optional[Dict[str, Collateral]] = None):
            self.pause = pause
            self.cdp_engine = cdp_engine
            self.acct_engine = acct_engine
            self.tax_collector = tax_collector
            self.liquidation_engine = liquidation_engine
            self.surplus_auction_house = surplus_auction_house
            self.debt_auction_house = debt_auction_house
            self.coin_savings_acct = coin_savings_acct
            self.dai = dai
            self.coin_join = coin_join
            self.gov = gov
            self.oracle_relayer = oracle_relayer
            self.ds_chief = ds_chief
            self.esm = esm
            self.end = end
            self.proxy_registry = proxy_registry
            self.proxy_actions = proxy_actions
            self.cdp_manager = cdp_manager
            #self.dsr_manager = dsr_manager
            self.collaterals = collaterals or {}

        @staticmethod
        def from_json(web3: Web3, conf: str):
            conf = json.loads(conf)
            pause = DSPause(web3, Address(conf['GEB_PAUSE']))
            cdp_engine = CDPEngine(web3, Address(conf['GEB_CDP_ENGINE']))
            acct_engine = AccountingEngine(web3, Address(conf['GEB_ACCOUNTING_ENGINE']))
            tax_collector = TaxCollector(web3, Address(conf['GEB_TAX_COLLECTOR']))
            liquidation_engine = LiquidationEngine(web3, Address(conf['GEB_LIQUIDATION_ENGINE']))
            dai = DSToken(web3, Address(conf['GEB_COIN']))#
            dai_adapter = CoinJoin(web3, Address(conf['GEB_COIN_JOIN']))#
            surplus_auction_house = SurplusAuctionHouse(web3, Address(conf['GEB_PRE_SETTLEMENT_SURPLUS_AUCTION_HOUSE']))
            debt_auction_house = DebtAuctionHouse(web3, Address(conf['GEB_DEBT_AUCTION_HOUSE']))
            coin_savings_acct = CoinSavingsAccount(web3, Address(conf['GEB_COIN']))
            gov = DSToken(web3, Address(conf['GEB_GOV']))
            oracle_relayer = OracleRelayer(web3, Address(conf['GEB_ORACLE_RELAYER']))
            #ds_chief = DSChief(web3, Address(conf['MCD_ADM']))
            ds_chief = DSChief(web3, Address(conf['GEB_ESM']))
            esm = ShutdownModule(web3, Address(conf['GEB_ESM']))
            end = End(web3, Address(conf['GEB_GLOBAL_SETTLEMENT']))
            proxy_registry = ProxyRegistry(web3, Address(conf['PROXY_REGISTRY']))
            proxy_actions = GebProxyActions(web3, Address(conf['PROXY_ACTIONS']))
            cdp_manager = CdpManager(web3, Address(conf['CDP_MANAGER']))
            #dsr_manager = DsrManager(web3, Address(conf['DSR_MANAGER']))#

            collaterals = {}
            for name in GfDeployment.Config._infer_collaterals_from_addresses(conf.keys()):
                collateral_type = CollateralType(name[0].replace('_', '-'))
                if name[1] == "ETH":
                    collateral = DSEthToken(web3, Address(conf[name[1]]))
                else:
                    collateral = DSToken(web3, Address(conf[name[1]]))

                if name[1] in ['USDC', 'WBTC', 'TUSD']:
                    adapter = CollateralJoin5(web3, Address(conf[f'GEB_JOIN_{name[0]}']))
                else:
                    adapter = CollateralJoin(web3, Address(conf[f'GEB_JOIN_{name[0]}']))

                # PIP contract may be a DSValue, OSM, or bogus address.
                pip_address = Address(conf[f'PIP_{name[1]}'])
                network = GfDeployment.NETWORKS.get(web3.net.version, "testnet")
                if network == "testnet":
                    pip = DSValue(web3, pip_address)
                else:
                    pip = OSM(web3, pip_address)

                collateral = Collateral(collateral_type=collateral_type, collateral=collateral, adapter=adapter,
                                        collateral_auction_house=CollateralAuctionHouse(web3, Address(conf[f'GEB_COLLATERAL_AUCTION_HOUSE_{name[0]}'])),
                                        pip=pip)
                collaterals[collateral_type.name] = collateral

            return GfDeployment.Config(pause, cdp_engine, acct_engine, tax_collector, liquidation_engine,
                                        surplus_auction_house, debt_auction_house, coin_savings_acct,
                                        dai, dai_adapter, gov, oracle_relayer, ds_chief, esm, end,
                                        proxy_registry, proxy_actions, cdp_manager,
                                        collaterals)

        @staticmethod
        def _infer_collaterals_from_addresses(keys: []) -> List:
            collaterals = []
            for key in keys:
                match = re.search(r'GEB_COLLATERAL_AUCTION_HOUSE_((\w+)_\w+)', key)
                if match:
                    collaterals.append((match.group(1), match.group(2)))
                    continue
                match = re.search(r'GEB_COLLATERAL_AUCTION_HOUSE_(\w+)', key)
                if match:
                    collaterals.append((match.group(1), match.group(1)))

            return collaterals

        def to_dict(self) -> dict:
            conf_dict = {
                'GEB_PAUSE': self.pause.address.address,
                'GEB_CDP_ENGINE': self.vat.address.address,
                'GEB_ACCOUNTING_ENGINE': self.vow.address.address,
                'GEB_TAX_COLLECTOR': self.jug.address.address,
                'GEB_LIQUIDATION_ENGINE': self.cat.address.address,
                'GEB_PRE_SETTLEMENT_SURPLUS_AUCTION_HOUSE': self.surplus_auction_house.address.address,
                'GEB_DEBT_AUCTION_HOUSE': self.debt_auction_house.address.address,
                #'MCD_POT': self.pot.address.address,
                'GEB_COIN': self.dai.address.address,
                'GEB_COIN_JOIN': self.coin_join.address.address,
                'GEB_GOV': self.mkr.address.address,
                'GEB_ORACLE_RELAYER': self.oracle_relayer.address.address,
                'MCD_ADM': self.ds_chief.address.address,
                'GEB_ESM': self.esm.address.address,
                'GEB_GLOBAL_SETTLEMENT': self.end.address.address,
                'PROXY_REGISTRY': self.proxy_registry.address.address,
                'PROXY_ACTIONS': self.proxy_actions.address.address,
                'CDP_MANAGER': self.cdp_manager.address.address
                 #'DSR_MANAGER': self.dsr_manager.address.address
            }

            for collateral in self.collaterals.values():
                match = re.search(r'(\w+)(?:-\w+)?', collateral.ilk.name)
                name = (collateral.collateral_type.name.replace('-', '_'), match.group(1))
                conf_dict[name[1]] = collateral.collateral.address.address
                if collateral.pip:
                    conf_dict[f'PIP_{name[1]}'] = collateral.pip.address.address
                conf_dict[f'GEB_JOIN_{name[0]}'] = collateral.adapter.address.address
                conf_dict[f'GEB_COLLATERAL_AUCTION_HOUSE_{name[0]}'] = collateral.flipper.address.address

            return conf_dict

        def to_json(self) -> str:
            return json.dumps(self.to_dict())

    def __init__(self, web3: Web3, config: Config):
        assert isinstance(web3, Web3)
        assert isinstance(config, GfDeployment.Config)

        self.web3 = web3
        self.config = config
        self.pause = config.pause
        self.cdp_engine = config.cdp_engine
        self.acct_engine = config.acct_engine
        self.tax_collector = config.tax_collector
        self.liquidation_engine = config.liquidation_engine
        self.surplus_auction_house = config.surplus_auction_house
        self.debt_auction_house = config.debt_auction_house
        self.coin_savings_acct = config.coin_savings_acct
        self.dai = config.dai
        self.dai_adapter = config.coin_join
        self.gov = config.gov
        self.collaterals = config.collaterals
        self.oracle_relayer = config.oracle_relayer
        self.ds_chief = config.ds_chief
        self.esm = config.esm
        self.end = config.end
        self.proxy_registry = config.proxy_registry
        self.proxy_actions = config.proxy_actions
        self.cdp_manager = config.cdp_manager
        #self.dsr_manager = config.dsr_manager

    @staticmethod
    def from_json(web3: Web3, conf: str):
        return GfDeployment(web3, GfDeployment.Config.from_json(web3, conf))

    def to_json(self) -> str:
        return self.config.to_json()

    @staticmethod
    def from_node(web3: Web3):
        assert isinstance(web3, Web3)

        network = GfDeployment.NETWORKS.get(web3.net.version, "testnet")

        return GfDeployment.from_network(web3=web3, network=network)

    @staticmethod
    def from_network(web3: Web3, network: str):
        assert isinstance(web3, Web3)
        assert isinstance(network, str)

        cwd = os.path.dirname(os.path.realpath(__file__))
        addresses_path = os.path.join(cwd, "../config", f"{network}-addresses.json")

        return GfDeployment.from_json(web3=web3, conf=open(addresses_path, "r").read())

    def approve_dai(self, usr: Address, **kwargs):
        """
        Allows the user to draw Dai from and repay Dai to their CDPs.

        Args
            usr: Recipient of Dai from one or more CDPs
        """
        assert isinstance(usr, Address)

        gas_price = kwargs['gas_price'] if 'gas_price' in kwargs else DefaultGasPrice()
        self.dai_adapter.approve(approval_function=approve_cdp_modification_directly(from_address=usr, gas_price=gas_price),
                                 source=self.cdp_engine.address)
        self.dai.approve(self.dai_adapter.address).transact(from_address=usr, gas_price=gas_price)

    def active_auctions(self) -> dict:
        flips = {}
        for collateral in self.collaterals.values():
            # Each collateral has it's own flip contract; add auctions from each.
            flips[collateral.collateral_type.name] = collateral.collateral_auction_house.active_auctions()

        return {
            "flips": flips,
            "flaps": self.surplus_auction_house.active_auctions(),
            "flops": self.debt_auction_house.active_auctions()
        }

    def __repr__(self):
        return f'GfDeployment({self.config.to_json()})'
