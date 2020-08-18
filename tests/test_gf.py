# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 bargst, EdNoepel
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
import pytest
import time
from datetime import datetime
from web3 import Web3

from pyflex import Address
from pyflex.approval import approve_cdp_modification_directly
from pyflex.deployment import GfDeployment
#from pyflex.gf import Collateral, CoinJoin, CollateralJoin, CollateralJoin5, CollateralType, CDP, CDPEngine, AccountingEngine
from pyflex.gf import Collateral, CoinJoin, CollateralJoin, CollateralType, CDP, CDPEngine, AccountingEngine
from pyflex.feed import DSValue
from pyflex.numeric import Wad, Ray, Rad
from pyflex.oracles import OSM
from pyflex.token import DSToken, DSEthToken, ERC20Token
from tests.conftest import validate_contracts_loaded


@pytest.fixture
def cdp(our_address: Address, geb: GfDeployment):
    collateral = geb.collaterals['ETH-A']
    return geb.cdp_engine.cdp(collateral.collateral_type, our_address)


def wrap_eth(geb: GfDeployment, address: Address, amount: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    collateral = geb.collaterals['ETH-A']
    assert isinstance(collateral.collateral, DSEthToken)
    assert collateral.collateral.deposit(amount).transact(from_address=address)

def mint_gov(gov: DSToken, recipient_address: Address, amount: Wad):
    assert isinstance(gov, DSToken)
    assert isinstance(recipient_address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    deployment_address = Address("0x00a329c0648769A73afAc7F9381E08FB43dBEA72")
    assert gov.mint(amount).transact(from_address=deployment_address)
    assert gov.balance_of(deployment_address) > Wad(0)
    assert gov.approve(recipient_address).transact(from_address=deployment_address)
    assert gov.transfer(recipient_address, amount).transact(from_address=deployment_address)

def get_collateral_price(collateral: Collateral):
    assert isinstance(collateral, Collateral)
    return Wad(Web3.toInt(collateral.pip.read()))


def set_collateral_price(geb: GfDeployment, collateral: Collateral, price: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    pip = collateral.pip
    assert isinstance(pip, DSValue)

    print(f"Changing price of {collateral.collateral_type.name} to {price}")
    assert pip.update_result_with_int(price.value).transact(from_address=pip.get_owner())
    assert geb.oracle_relayer.update_collateral_price(collateral_type=collateral.collateral_type).transact(from_address=pip.get_owner())

    assert get_collateral_price(collateral) == price


def wait(geb: GfDeployment, address: Address, seconds: int):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert seconds > 0

    time.sleep(seconds)
    # Mine a block to increment block.timestamp
    wrap_eth(geb, address, Wad(1))


def wrap_modify_cdp_collateralization(geb: GfDeployment, collateral: Collateral, address: Address, delta_collateral: Wad, delta_debt: Wad):
    """Wraps CDPEngine.modify_cdp_collateralization for debugging purposes"""
    # given
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    assert isinstance(delta_collateral, Wad)
    assert isinstance(delta_debt, Wad)
    collateral_type = collateral.collateral_type

    # when
    collateral_before = geb.cdp_engine.cdp(collateral_type, address).locked_collateral
    debt_before = geb.cdp_engine.cdp(collateral_type, address).generated_debt

    # then
    assert geb.cdp_engine.modify_cdp_collateralization(collateral_type=collateral_type, cdp_address=address,
                                                       delta_collateral=delta_collateral,
                                                       delta_debt=delta_debt).transact(from_address=address)

    assert geb.cdp_engine.cdp(collateral_type, address).locked_collateral == collateral_before + delta_collateral
    assert geb.cdp_engine.cdp(collateral_type, address).generated_debt == debt_before + delta_debt


def max_delta_debt(geb: GfDeployment, collateral: Collateral, our_address: Address) -> Wad:
    """Determines how much stablecoin should be reserved in an `cdp` to make it as poorly collateralized as
    possible, such that a small change to the collateral price could trip the liquidation ratio."""
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)

    # change in generated debt = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    delta_debt = cdp.locked_collateral * collateral_type.safety_price - Wad(Ray(cdp.generated_debt) * collateral_type.accumulated_rates)

    # change in debt must also take the rate into account
    delta_debt = delta_debt * Wad(Ray.from_number(1) / collateral_type.accumulated_rates)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(cdp.generated_debt) + Rad(delta_debt)) >= collateral_type.debt_ceiling:
        print("max_delta_debt is avoiding collateral debt ceiling")
        delta_debt = Wad(collateral_type.debt_ceiling - Rad(cdp.generated_debt))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = geb.cdp_engine.global_debt() + Rad(collateral_type.accumulated_rates * delta_debt)
    debt_ceiling = Rad(collateral_type.debt_ceiling)
    if (debt + Rad(delta_debt)) >= debt_ceiling:
        print("max_delta_debt is avoiding total debt ceiling")
        delta_debt = Wad(debt - Rad(cdp.generated_debt))

    assert delta_debt > Wad(0)
    return delta_debt


def cleanup_cdp(geb: GfDeployment, collateral: Collateral, address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, address)
    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)

    # If tax_collector.tax_single has been called, we won't have sufficient system_coin to repay the CDP
    #if collateral_type.accumulated_rates > Ray.from_number(1):
    #    return

    # Repay borrowed system coin
    geb.approve_system_coin(address)

    # Put all the user's system coin back into the cdp engine
    if geb.system_coin.balance_of(address) >= Wad(0):
        assert geb.system_coin_adapter.join(address, geb.system_coin.balance_of(address)).transact(from_address=address)

    # tab = Ray(cdp.generated_debt) * collateral_type.accumulated_rates
    # print(f'amount_to_raise={str(amount_to_raise)}, rate={str(collateral_type.accumulated_rates)}, system_coin={str(geb.cdp_engine.coin_balance(address))}')
    if cdp.generated_debt > Wad(0) and geb.cdp_engine.coin_balance(address) >= Rad(cdp.generated_debt):
        wrap_modify_cdp_collateralization(geb, collateral, address, Wad(0), cdp.generated_debt * -1)

    # Withdraw collateral
    collateral.approve(address)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, address)
    # delta_collateral = Wad((Ray(cdp.generated_debt) * collateral_type.accumulated_rates) / collateral_type.safety_price)
    # print(f'delta_collateral={str(delta_collateral)}, locked_collateral={str(cdp.locked_collateral)}')
    if cdp.generated_debt == Wad(0) and cdp.locked_collateral > Wad(0):
        wrap_modify_cdp_collateralization(geb, collateral, address, cdp.locked_collateral * -1, Wad(0))
    assert collateral.adapter.exit(address, geb.cdp_engine.token_collateral(collateral.collateral_type, address)).transact(from_address=address)
    # TestCDPEngine.ensure_clean_cdp(geb, collateral, address)


def simulate_liquidate_cdp(geb: GfDeployment, collateral: Collateral, our_address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

    # Collateral value should be less than the product of our stablecoin debt and the debt multiplier
    assert (Ray(cdp.locked_collateral) * collateral_type.safety_price) < (Ray(cdp.generated_debt) * collateral_type.accumulated_rates)

    # Lesser of our collateral balance and the liquidation quantity
    lot = min(cdp.locked_collateral, geb.liquidation_engine.collateral_to_sell(collateral_type))  # Wad

    # Lesser of our stablecoin debt and the canceled debt pro rata the seized collateral
    generated_debt = min(cdp.generated_debt, (lot * cdp.generated_debt) / cdp.locked_collateral)  # Wad

    # Stablecoin to be raised in collateral auction
    amount_to_raise = Ray(generated_debt) * collateral_type.accumulated_rates # Ray

    assert -int(lot) < 0 and -int(generated_debt) < 0
    assert amount_to_raise > Ray(0)


@pytest.fixture(scope="session")
def liquidate(web3: Web3, geb: GfDeployment, our_address: Address):
    collateral = geb.collaterals['ETH-A']

    # Add collateral to our CDP
    delta_collateral = Wad.from_number(1)
    wrap_eth(geb, our_address, delta_collateral)
    assert collateral.collateral.balance_of(our_address) >= delta_collateral
    assert collateral.adapter.join(our_address, delta_collateral).transact()
    wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral, Wad(0))

    # Define required liquidation parameters
    to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)

    # Manipulate price to make our CDP underwater
    # Note this will only work on a testchain deployed with fixed prices, where PIP is a DSValue
    wrap_modify_cdp_collateralization(geb, collateral, our_address, Wad(0), max_delta_debt(geb, collateral, our_address))
    set_collateral_price(geb, collateral, to_price)

    # Liquidate the CDP
    simulate_liquidation(geb, collateral, our_address)
    assert geb.liquidation_engine.liquidate_cdp(collateral.collateral_type, Urn(our_address)).transact()


@pytest.fixture(scope="session")
def liquidation_event(web3: Web3, geb: GfDeployment, our_address: Address):
    liquidate(web3, geb, our_address)
    # Return the corresponding event
    return geb.liquidation_engine.past_liquidationss(1)[0]


class TestConfig:
    def test_from_json(self, web3: Web3, geb: GfDeployment):
        # fixture calls GfDeployment.from_json
        assert len(geb.config.collaterals) >= 3
        assert len(geb.collaterals) >= 3
        assert len(geb.config.to_dict()) > 10
        assert len(geb.collaterals) == len(geb.config.collaterals)

    def test_to_json(self, web3: Web3, geb: GfDeployment):
        config_out = geb.to_json()
        dict = json.loads(config_out)
        assert "GEB_PROT" in dict
        assert "GEB_COIN" in dict
        assert len(dict) > 20

    def test_from_node(self, web3: Web3):
        geb_testnet = GfDeployment.from_node(web3)
        validate_contracts_loaded(geb_testnet)

    def test_collaterals(self, geb):
        for collateral in geb.collaterals.values():
            assert isinstance(collateral.collateral_type, CollateralType)
            assert isinstance(collateral.collateral, ERC20Token)
            assert len(collateral.collateral_type.name) > 0
            assert len(collateral.collateral.name()) > 0
            assert len(collateral.collateral.symbol()) > 0
            assert collateral.adapter is not None
            assert collateral.collateral_auction_house is not None
            assert collateral.pip is not None

    def test_account_transfers(self, web3: Web3, geb, our_address, other_address):
        collateral = geb.collaterals['ETH-A']
        token = collateral.collateral
        amount = Wad(10)

        assert web3.eth.defaultAccount == our_address.address
        assert our_address != other_address
        wrap_eth(geb, our_address, amount)

        # Move eth between each account to confirm keys are properly set up
        before = token.balance_of(our_address)
        assert token.transfer_from(our_address, other_address, amount).transact()
        after = token.balance_of(our_address)
        assert (before - amount) == after

        assert token.transfer_from(other_address, our_address, amount).transact(from_address=other_address)
        assert token.balance_of(our_address) == before

    def test_get_active_auctions(self, geb):
        auctions = geb.active_auctions()
        assert "collateral_auctions" in auctions
        assert "surplus_auctions" in auctions
        assert "debt_auctions" in auctions


class TestCDPEngine:
    @staticmethod
    def ensure_clean_cdp(geb: GfDeployment, collateral: Collateral, address: Address):
        assert isinstance(geb, GfDeployment)
        assert isinstance(collateral, Collateral)
        assert isinstance(address, Address)

        cdp = geb.cdp_engine.cdp(collateral.collateral_type, address)
        assert cdp.locked_collateral == Wad(0)
        assert cdp.generated_debt == Wad(0)
        assert geb.cdp_engine.token_collateral(collateral.collateral_type, address) == Wad(0)

    def test_getters(self, geb):
        assert isinstance(geb.cdp_engine.contract_enabled(), bool)

    def test_collateral_type(self, geb):
        assert geb.cdp_engine.collateral_type('XXX') == CollateralType('XXX',
                                         accumulated_rates=Ray(0), cdp_collateral=Wad(0), cdp_debt=Wad(0),
                                         safety_price=Ray(0), debt_ceiling=Rad(0), debt_floor=Rad(0))

    def test_collateral(self, web3: Web3, geb: GfDeployment, our_address: Address):
        # given
        collateral = geb.collaterals['ETH-A']
        amount_to_join = Wad(10)
        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        assert isinstance(collateral.collateral_type, CollateralType)
        assert isinstance(collateral.adapter, CollateralJoin)
        assert collateral.collateral_type == collateral.adapter.collateral_type()
        assert our_cdp.address == our_address
        wrap_eth(geb, our_address, amount_to_join)
        assert collateral.collateral.balance_of(our_address) >= amount_to_join

        # when
        before_join = geb.cdp_engine.token_collateral(collateral.collateral_type, our_cdp.address)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, amount_to_join).transact()
        after_join = geb.cdp_engine.token_collateral(collateral.collateral_type, our_cdp.address)
        assert collateral.adapter.exit(our_address, amount_to_join).transact()
        after_exit = geb.cdp_engine.token_collateral(collateral.collateral_type, our_cdp.address)

        # then
        assert after_join - before_join == amount_to_join
        assert after_exit == before_join

    def test_collateral_join(self, geb: GfDeployment):
        pass
        #collateral_bat = geb.collaterals['BAT-A']
        #assert isinstance(collateral_bat.adapter, CollateralJoin)
        #assert collateral_bat.adapter.dec() == 18


    def test_coin_balance(self, geb, cdp):
        coin_balance = geb.cdp_engine.coin_balance(cdp.address)
        assert coin_balance >= Rad(0)

    def test_debt_balance(self, geb, cdp):
        debt_balance = geb.cdp_engine.debt_balance(cdp.address)
        assert isinstance(debt_balance, Rad)
        assert debt_balance == Rad(0)

    def test_debt(self, geb):
        debt = geb.cdp_engine.global_debt()
        assert debt >= Rad(0)
        assert debt < geb.cdp_engine.global_debt_ceiling()

    def test_modify_cdp_collateralization_noop(self, geb, our_address):
        # given
        collateral = geb.collaterals['ETH-A']
        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, our_address, Wad(0), Wad(0)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address) == our_cdp

    #@pytest.mark.skip('temp')
    def test_modify_cdp_collateralization_add_collateral(self, geb, our_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        wrap_eth(geb, our_address, Wad(10))
        assert collateral.adapter.join(our_address, Wad(10)).transact()
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, our_address, Wad(10), Wad(0)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address).locked_collateral == our_cdp.locked_collateral + Wad(10)

        # rollback
        cleanup_cdp(geb, collateral, our_address)

    #@pytest.mark.skip('temp')
    def test_modify_cdp_collateralization_add_debt(self, geb, our_address: Address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        wrap_eth(geb, our_address, Wad.from_number(30))

        assert collateral.adapter.join(our_address, Wad.from_number(30)).transact()
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, our_address, Wad.from_number(30), Wad.from_number(20)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address).generated_debt == our_cdp.generated_debt + Wad.from_number(20)

        # rollback
        cleanup_cdp(geb, collateral, our_address)

    #@pytest.mark.skip('temp')
    def test_modify_cdp_collateralization_other_account(self, web3, geb, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(other_address)
        geb.system_coin_adapter.approve(approve_cdp_modification_directly(from_address=other_address), geb.cdp_engine.address)
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert cdp.address == other_address

        # when
        wrap_eth(geb, other_address, Wad.from_number(100 ))
        assert collateral.collateral.balance_of(other_address) >= Wad.from_number(100)
        assert collateral.collateral == collateral.adapter.collateral()
        collateral.collateral.approve(collateral.adapter.address)
        assert collateral.adapter.join(other_address, Wad.from_number(30)).transact(from_address=other_address)
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, other_address,
                                                           Wad.from_number(30), Wad.from_number(20)).transact(from_address=other_address)

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, other_address).generated_debt == cdp.generated_debt + Wad.from_number(20)

        # rollback
        cleanup_cdp(geb, collateral, other_address)

    def test_past_modify_cdp_collateralization(self, geb, our_address, other_address):
        # given
        collateral0 = geb.collaterals['ETH-B']
        collateral_type0 = collateral0.collateral_type
        collateral1 = geb.collaterals['ETH-C']
        collateral_type1 = collateral1.collateral_type

        try:
            # when
            wrap_eth(geb, our_address, Wad.from_number(180))
            wrap_eth(geb, other_address, Wad.from_number(180))

            collateral0.approve(our_address)
            assert collateral0.adapter.join(our_address, Wad.from_number(90)).transact()
            assert geb.cdp_engine.modify_cdp_collateralization(collateral_type0, our_address, Wad.from_number(30), Wad(0)).transact()

            collateral1.approve(other_address)
            assert collateral1.adapter.join(other_address, Wad.from_number(90)).transact(from_address=other_address)
            assert geb.cdp_engine.modify_cdp_collateralization(collateral_type1, other_address, Wad.from_number(90), Wad(0)).transact(from_address=other_address)
            assert geb.cdp_engine.modify_cdp_collateralization(collateral_type1, other_address, Wad.from_number(-30), Wad(0)).transact(from_address=other_address)

            assert geb.cdp_engine.modify_cdp_collateralization(collateral_type1, our_address, Wad.from_number(30), Wad(0),
                                collateral_owner=other_address, system_coin_recipient=other_address).transact(
                from_address=other_address)

            # then
            current_block = geb.web3.eth.blockNumber
            from_block = current_block - 6
            mods = geb.cdp_engine.past_cdp_modifications(from_block)
            assert len(mods) == 4
            assert mods[0].collateral_type == collateral_type0.name
            assert mods[0].cdp == our_address
            assert mods[0].delta_collateral == Wad.from_number(30)
            assert mods[0].delta_debt == Wad(0)
            assert mods[1].collateral_type == collateral_type1.name
            assert mods[1].cdp == other_address
            assert mods[1].delta_collateral == Wad.from_number(90)
            assert mods[1].delta_debt == Wad(0)
            assert mods[2].collateral_type == collateral_type1.name
            assert mods[2].cdp == other_address
            assert mods[2].delta_collateral == Wad.from_number(-30)
            assert mods[2].delta_debt == Wad(0)
            assert mods[3].cdp == our_address
            assert mods[3].collateral_source == other_address
            assert mods[3].delta_collateral == Wad.from_number(30)
            assert mods[3].delta_debt == Wad(0)

            assert len(geb.cdp_engine.past_cdp_modifications(from_block, collateral_type=collateral_type0)) == 1
            assert len(geb.cdp_engine.past_cdp_modifications(from_block, collateral_type=collateral_type1)) == 3

        finally:
            # teardown
            cleanup_cdp(geb, collateral0, our_address)
            TestCDPEngine.ensure_clean_cdp(geb, collateral0, our_address)
            cleanup_cdp(geb, collateral1, other_address)
            TestCDPEngine.ensure_clean_cdp(geb, collateral1, other_address)

    def test_settle_debt(self, geb):
        assert geb.cdp_engine.settle_debt(Rad(0)).transact()

    def test_transfer_collateral(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        other_balance_before = geb.cdp_engine.token_collateral(collateral.collateral_type, other_address)
        amount = Wad(3)
        wrap_eth(geb, our_address, amount)
        assert collateral.adapter.join(our_address, amount).transact()

        # when
        assert geb.cdp_engine.transfer_collateral(collateral.collateral_type, our_address, other_address, amount).transact()

        # then
        other_balance_after = geb.cdp_engine.token_collateral(collateral.collateral_type, other_address)
        assert Wad(other_balance_before) + amount == Wad(other_balance_after)

        # teardown
        cleanup_cdp(geb, collateral, our_address)

    def test_transfer_internal_coins(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        wrap_eth(geb, our_address, Wad.from_number(60))

        assert collateral.adapter.join(our_address, Wad.from_number(60)).transact()
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, our_address, Wad.from_number(60), Wad.from_number(20)).transact()
        other_balance_before = geb.cdp_engine.coin_balance(other_address)

        # when
        assert geb.cdp_engine.transfer_internal_coins(our_address, other_address, Rad(Wad.from_number(20))).transact()

        # then
        other_balance_after = geb.cdp_engine.coin_balance(other_address)
        assert other_balance_before + Rad(Wad.from_number(20)) == other_balance_after

        # rollback
        cleanup_cdp(geb, collateral, our_address)

    def test_transfer_cdp_collateral_and_debt(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        geb.cdp_engine.approve_cdp_modification(our_address).transact(from_address=other_address)
        geb.cdp_engine.approve_cdp_modification(other_address).transact(from_address=our_address)

        our_cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        wrap_eth(geb, our_address, Wad.from_number(60))
        assert collateral.adapter.join(our_address, Wad.from_number(60)).transact()
        assert geb.cdp_engine.modify_cdp_collateralization(collateral.collateral_type, our_address, Wad.from_number(60), Wad.from_number(20)).transact()
        cdp_before = geb.cdp_engine.cdp(collateral.collateral_type, other_address)

        # when
        assert geb.cdp_engine.transfer_cdp_collateral_and_debt(collateral.collateral_type, our_address, other_address, Wad.from_number(3), Wad.from_number(20)).transact()

        # then
        cdp_after = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert cdp_before.locked_collateral + Wad.from_number(3) == cdp_after.locked_collateral
        assert cdp_before.generated_debt + Wad.from_number(20) == cdp_after.generated_debt

        # rollback
        cleanup_cdp(geb, collateral, our_address)


class TestLiquidationEngine:
    def test_getters(self, geb):
        assert isinstance(geb.liquidation_engine.contract_enabled(), bool)
        assert isinstance(geb.liquidation_engine.cdp_engine, CDPEngine)
        assert isinstance(geb.liquidation_engine.accounting_engine, AccountingEngine)

        collateral = geb.collaterals['ETH-C']
        assert geb.liquidation_engine.collateral_auction_house(collateral.collateral_type) == collateral.collateral_auction_house.address
        assert isinstance(geb.liquidation_engine.collateral_to_sell(collateral.collateral_type), Wad)
        assert isinstance(geb.liquidation_engine.liquidation_penalty(collateral.collateral_type), Ray)


class TestOracleRelayer:
    def test_safety_c_ratio(self, geb):
        val = Ray(geb.collaterals['ETH-A'].pip.read_as_int())

        collateral_type = geb.cdp_engine.collateral_type('ETH-A')
        redemption_price = geb.oracle_relayer.redemption_price()
        safe_c_ratio = geb.oracle_relayer.safety_c_ratio(collateral_type)
        liquidation_c_ratio = geb.oracle_relayer.liquidation_c_ratio(collateral_type)

        assert safe_c_ratio == (Ray(val * 10 ** 9) / redemption_price) / (collateral_type.safety_price)

class TestAccountingEngine:
    def test_getters(self, geb):
        assert isinstance(geb.accounting_engine.cdp_engine, CDPEngine)
        assert isinstance(geb.accounting_engine.contract_enabled(), bool)
        assert isinstance(geb.accounting_engine.surplus_auction_house(), Address)
        assert isinstance(geb.accounting_engine.debt_auction_house(), Address)
        assert isinstance(geb.accounting_engine.debt_queue(), Rad)
        assert isinstance(geb.accounting_engine.debt_queue_of(0), Rad)
        assert isinstance(geb.accounting_engine.total_on_auction_debt(), Rad)
        assert isinstance(geb.accounting_engine.unqueued_unauctioned_debt(), Rad)
        assert isinstance(geb.accounting_engine.pop_debt_delay(), int)
        assert isinstance(geb.accounting_engine.initial_debt_auction_minted_tokens(), Wad)
        assert isinstance(geb.accounting_engine.debt_auction_bid_size(), Rad)
        assert isinstance(geb.accounting_engine.surplus_auction_amount_to_sell(), Rad)
        assert isinstance(geb.accounting_engine.surplus_buffer(), Rad)

    def test_empty_flog(self, geb):
        assert geb.accounting_engine.pop_debt_from_queue(0).transact()

    def test_settle_debt(self, geb):
        assert geb.accounting_engine.settle_debt(Rad(0)).transact()

    def test_cancel_auctioned_debt_with_surplus(self, geb):
        assert geb.accounting_engine.cancel_auctioned_debt_with_surplus(Rad(0)).transact()


class TestTaxCollector:
    def test_getters(self, geb):
        c = geb.collaterals['ETH-A']
        assert isinstance(geb.tax_collector.cdp_engine, CDPEngine)
        assert isinstance(geb.tax_collector.accounting_engine, AccountingEngine)
        assert isinstance(geb.tax_collector.global_stability_fee(), Ray)
        assert isinstance(geb.tax_collector.stability_fee(c.collateral_type), Ray)
        assert isinstance(geb.tax_collector.update_time(c.collateral_type), int)

    def test_tax_single(self, geb):
        # given
        c = geb.collaterals['ETH-A']

        # then
        assert geb.tax_collector.tax_single(c.collateral_type).transact()

class TestPot:
    def test_getters(self, mcd):
        assert isinstance(mcd.pot.pie(), Wad)
        assert isinstance(mcd.pot.dsr(), Ray)
        assert isinstance(mcd.pot.rho(), datetime)

        assert mcd.pot.pie() >= Wad(0)
        assert mcd.pot.dsr() > Ray(0)
        assert datetime.fromtimestamp(0) < mcd.pot.rho() < datetime.utcnow()

    def test_drip(self, mcd):
        assert mcd.pot.drip().transact()

class TestOsm:
    def test_price(self, web3, geb):
        collateral = geb.collaterals['ETH-B']
        set_collateral_price(geb, collateral, Wad.from_number(200))
        # Note this isn't actually an OSM, but we can still read storage slots
        osm = OSM(web3, collateral.pip.address)
        raw_price = osm._extract_price(2)
        assert isinstance(raw_price, int)
        assert Wad.from_number(200) == Wad(raw_price)


class TestGeb:
    def test_healthy_cdp(self, web3, geb, our_address):
        collateral = geb.collaterals['ETH-B']
        collateral_type = collateral.collateral_type
        TestCDPEngine.ensure_clean_cdp(geb, collateral, our_address)
        initial_system_coin = geb.cdp_engine.coin_balance(our_address)
        wrap_eth(geb, our_address, Wad.from_number(90))

        # Ensure our collateral enters the cdp
        collateral_balance_before = collateral.collateral.balance_of(our_address)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, Wad.from_number(90)).transact()
        assert collateral.collateral.balance_of(our_address) == collateral_balance_before - Wad.from_number(90)

        # Add collateral without generating system coin
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad.from_number(30), delta_debt=Wad(0))
        print(f"After adding collateral:         {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral == Wad.from_number(30)
        assert geb.cdp_engine.cdp(collateral_type, our_address).generated_debt == Wad(0)
        assert geb.cdp_engine.token_collateral(collateral_type, our_address) == Wad.from_number(90) - geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral
        assert geb.cdp_engine.coin_balance(our_address) == initial_system_coin

        # Generate some system coin
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad(0), delta_debt=Wad.from_number(153))
        return
        print(f"After generating system_coin:            {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral == Wad.from_number(30)
        assert geb.cdp_engine.cdp(collateral_type, our_address).generated_debt == Wad.from_number(153)
        assert geb.cdp_engine.coin_balance(our_address) == initial_system_coin + Rad.from_number(153)

        # Add collateral and generate some more system coin
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad.from_number(60), delta_debt=Wad.from_number(180))
        print(f"After adding collateral and system_coin: {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral == Wad.from_number(90)
        assert geb.cdp_engine.token_collateral(collateral_type, our_address) == Wad(0)
        assert geb.cdp_engine.cdp(collateral_type, our_address).generated_debt == Wad.from_number(333)
        assert geb.cdp_engine.coin_balance(our_address) == initial_system_coin + Rad.from_number(333)

        # Mint and withdraw our system coin
        system_coin_balance_before = geb.system_coin.balance_of(our_address)
        geb.approve_system_coin(our_address)
        assert isinstance(geb.system_coin_adapter, CoinJoin)
        assert geb.system_coin_adapter.exit(our_address, Wad.from_number(333)).transact()
        assert geb.system_coin.balance_of(our_address) == system_coin_balance_before + Wad.from_number(333)
        assert geb.cdp_engine.coin_balance(our_address) == initial_system_coin
        assert geb.cdp_engine.global_debt() >= initial_system_coin + Rad.from_number(333)

        # Repay (and burn) our system coin
        assert geb.system_coin_adapter.join(our_address, Wad.from_number(333)).transact()
        assert geb.system_coin.balance_of(our_address) == Wad(0)
        assert geb.cdp_engine.coin_balance(our_address) == initial_system_coin + Rad.from_number(333)

        # Withdraw our collateral
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad(0), delta_debt=Wad.from_number(-333))
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad.from_number(-90), delta_debt=Wad(0))
        assert geb.cdp_engine.token_collateral(collateral_type, our_address) == Wad.from_number(90)
        assert collateral.adapter.exit(our_address, Wad.from_number(90)).transact()
        collateral_balance_after = collateral.collateral.balance_of(our_address)
        assert collateral_balance_before == collateral_balance_after

        # Cleanup
        cleanup_cdp(geb, collateral, our_address)
