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
from pyflex.approval import hope_directly
from pyflex.deployment import DssDeployment
from pyflex.dss import Collateral, DaiJoin, GemJoin, GemJoin5, Ilk, Urn, Vat, Vow
from pyflex.feed import DSValue
from pyflex.numeric import Wad, Ray, Rad
from pyflex.oracles import OSM
from pyflex.token import DSToken, DSEthToken, ERC20Token
from tests.conftest import validate_contracts_loaded


@pytest.fixture
def cdp(our_address: Address, geb: DssDeployment):
    collateral = geb.collaterals['ETH-A']
    return geb.cdp_engine.cdp(collateral.collateral_type, our_address)


def wrap_eth(geb: DssDeployment, address: Address, amount: Wad):
    assert isinstance(geb, DssDeployment)
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


def set_collateral_price(geb: DssDeployment, collateral: Collateral, price: Wad):
    assert isinstance(geb, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    pip = collateral.pip
    assert isinstance(pip, DSValue)

    print(f"Changing price of {collateral.collateral_type.name} to {price}")
    assert pip.poke_with_int(price.value).transact(from_address=pip.get_owner())
    assert geb.oracle_relayer.update_collateral_price(collateral_type=collateral.collateral_type).transact(from_address=pip.get_owner())

    assert get_collateral_price(collateral) == price


def wait(geb: DssDeployment, address: Address, seconds: int):
    assert isinstance(geb, DssDeployment)
    assert isinstance(address, Address)
    assert seconds > 0

    time.sleep(seconds)
    # Mine a block to increment block.timestamp
    wrap_eth(geb, address, Wad(1))


def frob(geb: DssDeployment, collateral: Collateral, address: Address, dink: Wad, dart: Wad):
    """Wraps vat.frob for debugging purposes"""
    # given
    assert isinstance(geb, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    assert isinstance(dink, Wad)
    assert isinstance(dart, Wad)
    collateral_type = collateral.collateral_type

    # when
    collateral_before = geb.cdp_engine.cdp(collateral_type, address).locked_collateral
    debt_before = geb.cdp_engine.cdp(collateral_type, address).generated_debt

    # then
    assert geb.cdp_engine.frob(collateral_type=collateral_type, cdp_address=address, dink=dink, dart=dart).transact(from_address=address)
    assert geb.cdp_engine.cdp(collateral_type, address).locked_collateral == collateral_before + dink
    assert geb.cdp_engine.cdp(collateral_type, address).generated_debt == debt_before + dart


def max_dart(geb: DssDeployment, collateral: Collateral, our_address: Address) -> Wad:
    """Determines how much stablecoin should be reserved in an `urn` to make it as poorly collateralized as
    possible, such that a small change to the collateral price could trip the liquidation ratio."""
    assert isinstance(geb, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)

    # change in art = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    dart = cdp.ink * collateral_type.spot - Wad(Ray(cdp.art) * collateral_type.rate)

    # change in debt must also take the rate into account
    dart = dart * Wad(Ray.from_number(1) / collateral_type.rate)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(cdp.generated_debt) + Rad(dart)) >= collateral_type.debt_ceiling:
        print("max_dart is avoiding collateral debt ceiling")
        dart = Wad(collateral_type.debt_ceiling - Rad(cdp.generated_debt))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = geb.cdp_engine.debt() + Rad(collateral_type.rate * dart)
    debt_ceiling = Rad(collateral_type.debt_ceiling)
    if (debt + Rad(dart)) >= debt_ceiling:
        print("max_dart is avoiding total debt ceiling")
        dart = Wad(debt - Rad(cdp.generated_debt))

    assert dart > Wad(0)
    return dart


def cleanup_cdp(geb: DssDeployment, collateral: Collateral, address: Address):
    assert isinstance(geb, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, address)
    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)

    # If tax_collector.drip has been called, we won't have sufficient dai to repay the CDP
    if collateral_type.rate > Ray.from_number(1):
        return

    # Repay borrowed Dai
    geb.approve_dai(address)
    # Put all the user's Dai back into the vat
    if geb.dai.balance_of(address) >= Wad(0):
        assert geb.dai_adapter.join(address, geb.dai.balance_of(address)).transact(from_address=address)
    # tab = Ray(urn.art) * collateral_type.rate
    # print(f'tab={str(tab)}, rate={str(collateral_type.rate)}, dai={str(geb.cdp_engine.coin_balance(address))}')
    if urn.art > Wad(0) and geb.cdp_engine.coin_balance(address) >= Rad(urn.art):
        frob(geb, collateral, address, Wad(0), urn.art * -1)

    # Withdraw collateral
    collateral.approve(address)
    urn = geb.cdp_engine.cdp(collateral.collateral_type, address)
    # dink = Wad((Ray(urn.art) * collateral_type.rate) / collateral_type.spot)
    # print(f'dink={str(dink)}, ink={str(urn.ink)}')
    if urn.art == Wad(0) and urn.ink > Wad(0):
        frob(geb, collateral, address, urn.ink * -1, Wad(0))
    assert collateral.adapter.exit(address, geb.cdp_engine.collateral(collateral.collateral_type, address)).transact(from_address=address)
    # TestVat.ensure_clean_urn(geb, collateral, address)


def simulate_bite(geb: DssDeployment, collateral: Collateral, our_address: Address):
    assert isinstance(geb, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    collateral_type = geb.cdp_engine.collateral_type(collateral.collateral_type.name)
    urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

    # Collateral value should be less than the product of our stablecoin debt and the debt multiplier
    assert (Ray(urn.ink) * collateral_type.spot) < (Ray(urn.art) * collateral_type.rate)

    # Lesser of our collateral balance and the liquidation quantity
    lot = min(urn.ink, geb.cat.lump(collateral_type))  # Wad
    # Lesser of our stablecoin debt and the canceled debt pro rata the seized collateral
    art = min(urn.art, (lot * urn.art) / urn.ink)  # Wad
    # Stablecoin to be raised in flip auction
    tab = Ray(art) * collateral_type.rate  # Ray

    assert -int(lot) < 0 and -int(art) < 0
    assert tab > Ray(0)


@pytest.fixture(scope="session")
def bite(web3: Web3, geb: DssDeployment, our_address: Address):
    collateral = geb.collaterals['ETH-A']

    # Add collateral to our CDP
    dink = Wad.from_number(1)
    wrap_eth(geb, our_address, dink)
    assert collateral.gem.balance_of(our_address) >= dink
    assert collateral.adapter.join(our_address, dink).transact()
    frob(geb, collateral, our_address, dink, Wad(0))

    # Define required bite parameters
    to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)

    # Manipulate price to make our CDP underwater
    # Note this will only work on a testchain deployed with fixed prices, where PIP is a DSValue
    frob(geb, collateral, our_address, Wad(0), max_dart(geb, collateral, our_address))
    set_collateral_price(geb, collateral, to_price)

    # Bite the CDP
    simulate_bite(geb, collateral, our_address)
    assert geb.cat.bite(collateral.collateral_type, Urn(our_address)).transact()


@pytest.fixture(scope="session")
def bite_event(web3: Web3, geb: DssDeployment, our_address: Address):
    bite(web3, geb, our_address)
    # Return the corresponding event
    return geb.cat.past_bites(1)[0]


class TestConfig:
    def test_from_json(self, web3: Web3, geb: DssDeployment):
        # fixture calls DssDeployment.from_json
        assert len(geb.config.collaterals) >= 3
        assert len(geb.collaterals) >= 3
        assert len(geb.config.to_dict()) > 10
        assert len(geb.collaterals) == len(geb.config.collaterals)

    def test_to_json(self, web3: Web3, geb: DssDeployment):
        config_out = geb.to_json()
        dict = json.loads(config_out)
        assert "MCD_GOV" in dict
        assert "MCD_DAI" in dict
        assert len(dict) > 20

    def test_from_node(self, web3: Web3):
        geb_testnet = DssDeployment.from_node(web3)
        validate_contracts_loaded(geb_testnet)

    def test_collaterals(self, geb):
        for collateral in geb.collaterals.values():
            assert isinstance(collateral.collateral_type, Ilk)
            assert isinstance(collateral.gem, ERC20Token)
            assert len(collateral.collateral_type.name) > 0
            assert len(collateral.gem.name()) > 0
            assert len(collateral.gem.symbol()) > 0
            assert collateral.adapter is not None
            assert collateral.flipper is not None
            assert collateral.pip is not None

    def test_account_transfers(self, web3: Web3, geb, our_address, other_address):
        print(geb.collaterals)
        collateral = geb.collaterals['ETH-A']
        token = collateral.gem
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
        assert "flips" in auctions
        assert "flaps" in auctions
        assert "flops" in auctions


class TestVat:
    @staticmethod
    def ensure_clean_cdp(geb: DssDeployment, collateral: Collateral, address: Address):
        assert isinstance(geb, DssDeployment)
        assert isinstance(collateral, Collateral)
        assert isinstance(address, Address)

        urn = geb.cdp_engine.cdp(collateral.collateral_type, address)
        assert urn.ink == Wad(0)
        assert urn.art == Wad(0)
        assert geb.cdp_engine.collateral(collateral.collateral_type, address) == Wad(0)


    def test_getters(self, geb):
        assert isinstance(geb.cdp_engine.live(), bool)

    def test_collateral_type(self, geb):
        assert geb.cdp_engine.collateral_type('XXX') == Ilk('XXX',
                                         rate=Ray(0), ink=Wad(0), art=Wad(0), spot=Ray(0), line=Rad(0), dust=Rad(0))

    def test_gem(self, web3: Web3, geb: DssDeployment, our_address: Address):
        # given
        collateral = geb.collaterals['ETH-A']
        amount_to_join = Wad(10)
        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        assert isinstance(collateral.collateral_type, Ilk)
        assert isinstance(collateral.adapter, GemJoin)
        assert collateral.collateral_type == collateral.adapter.collateral_type()
        assert our_urn.address == our_address
        wrap_eth(geb, our_address, amount_to_join)
        assert collateral.gem.balance_of(our_address) >= amount_to_join

        # when
        before_join = geb.cdp_engine.collateral(collateral.collateral_type, our_urn.address)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, amount_to_join).transact()
        after_join = geb.cdp_engine.collateral(collateral.collateral_type, our_urn.address)
        assert collateral.adapter.exit(our_address, amount_to_join).transact()
        after_exit = geb.cdp_engine.collateral(collateral.collateral_type, our_urn.address)

        # then
        assert after_join - before_join == amount_to_join
        assert after_exit == before_join

    def test_gem_join(self, geb: DssDeployment):
        collateral_bat = geb.collaterals['BAT-A']
        assert isinstance(collateral_bat.adapter, GemJoin)
        assert collateral_bat.adapter.dec() == 18

        collateral_usdc = geb.collaterals['USDC-A']
        assert isinstance(collateral_usdc.adapter, GemJoin5)
        assert collateral_usdc.adapter.dec() == 6

    def test_dai(self, geb, urn):
        dai = geb.cdp_engine.coin_balance(urn.address)
        assert dai >= Rad(0)

    def test_sin(self, geb, urn):
        sin = geb.cdp_engine.sin(urn.address)
        assert isinstance(sin, Rad)
        assert sin == Rad(0)

    def test_debt(self, geb):
        debt = geb.cdp_engine.debt()
        assert debt >= Rad(0)
        assert debt < geb.cdp_engine.line()

    def test_frob_noop(self, geb, our_address):
        # given
        collateral = geb.collaterals['ETH-A']
        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        assert geb.cdp_engine.frob(collateral.collateral_type, our_address, Wad(0), Wad(0)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address) == our_urn

    def test_frob_add_ink(self, geb, our_address):
        # given
        collateral = geb.collaterals['ETH-A']
        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        wrap_eth(geb, our_address, Wad(10))
        assert collateral.adapter.join(our_address, Wad(10)).transact()
        assert geb.cdp_engine.frob(collateral.collateral_type, our_address, Wad(10), Wad(0)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address).ink == our_urn.ink + Wad(10)

        # rollback
        cleanup_urn(geb, collateral, our_address)

    def test_frob_add_art(self, geb, our_address: Address):
        # given
        collateral = geb.collaterals['ETH-A']
        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)

        # when
        wrap_eth(geb, our_address, Wad(10))
        assert collateral.adapter.join(our_address, Wad(3)).transact()
        assert geb.cdp_engine.frob(collateral.collateral_type, our_address, Wad(3), Wad(10)).transact()

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, our_address).art == our_urn.art + Wad(10)

        # rollback
        cleanup_urn(geb, collateral, our_address)

    def test_frob_other_account(self, web3, geb, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(other_address)
        geb.dai_adapter.approve(hope_directly(from_address=other_address), geb.cdp_engine.address)
        urn = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert urn.address == other_address

        # when
        wrap_eth(geb, other_address, Wad(10))
        assert collateral.gem.balance_of(other_address) >= Wad(10)
        assert collateral.gem == collateral.adapter.gem()
        collateral.gem.approve(collateral.adapter.address)
        assert collateral.adapter.join(other_address, Wad(3)).transact(from_address=other_address)
        assert geb.cdp_engine.frob(collateral.collateral_type, other_address, Wad(3), Wad(10)).transact(from_address=other_address)

        # then
        assert geb.cdp_engine.cdp(collateral.collateral_type, other_address).art == urn.art + Wad(10)

        # rollback
        cleanup_urn(geb, collateral, other_address)

    def test_past_frob(self, geb, our_address, other_address):
        # given
        collateral0 = geb.collaterals['ETH-B']
        collateral_type0 = collateral0.collateral_type
        collateral1 = geb.collaterals['ETH-C']
        collateral_type1 = collateral1.collateral_type

        try:
            # when
            wrap_eth(geb, our_address, Wad(18))
            wrap_eth(geb, other_address, Wad(18))

            collateral0.approve(our_address)
            assert collateral0.adapter.join(our_address, Wad(9)).transact()
            assert geb.cdp_engine.frob(collateral_type0, our_address, Wad(3), Wad(0)).transact()

            collateral1.approve(other_address)
            assert collateral1.adapter.join(other_address, Wad(9)).transact(from_address=other_address)
            assert geb.cdp_engine.frob(collateral_type1, other_address, Wad(9), Wad(0)).transact(from_address=other_address)
            assert geb.cdp_engine.frob(collateral_type1, other_address, Wad(-3), Wad(0)).transact(from_address=other_address)

            assert geb.cdp_engine.frob(collateral_type1, our_address, Wad(3), Wad(0),
                                collateral_owner=other_address, dai_recipient=other_address).transact(
                from_address=other_address)

            # then
            current_block = geb.web3.eth.blockNumber
            from_block = current_block - 6
            frobs = geb.cdp_engine.past_frobs(from_block)
            assert len(frobs) == 4
            assert frobs[0].collateral_type == collateral_type0.name
            assert frobs[0].urn == our_address
            assert frobs[0].dink == Wad(3)
            assert frobs[0].dart == Wad(0)
            assert frobs[1].collateral_type == collateral_type1.name
            assert frobs[1].urn == other_address
            assert frobs[1].dink == Wad(9)
            assert frobs[1].dart == Wad(0)
            assert frobs[2].collateral_type == collateral_type1.name
            assert frobs[2].urn == other_address
            assert frobs[2].dink == Wad(-3)
            assert frobs[2].dart == Wad(0)
            assert frobs[3].urn == our_address
            assert frobs[3].collateral_owner == other_address
            assert frobs[3].dink == Wad(3)
            assert frobs[3].dart == Wad(0)

            assert len(geb.cdp_engine.past_frobs(from_block, collateral_type=collateral_type0)) == 1
            assert len(geb.cdp_engine.past_frobs(from_block, collateral_type=collateral_type1)) == 3
            assert len(geb.cdp_engine.past_frobs(from_block, collateral_type=geb.collaterals['USDC-A'].collateral_type)) == 0

        finally:
            # teardown
            cleanup_urn(geb, collateral0, our_address)
            cleanup_urn(geb, collateral1, other_address)

    def test_heal(self, geb):
        assert geb.cdp_engine.heal(Rad(0)).transact()

    def test_flux(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        other_balance_before = geb.cdp_engine.collateral(collateral.collateral_type, other_address)
        amount = Wad(3)
        wrap_eth(geb, our_address, amount)
        assert collateral.adapter.join(our_address, amount).transact()

        # when
        assert geb.cdp_engine.flux(collateral.collateral_type, our_address, other_address, amount).transact()

        # then
        other_balance_after = geb.cdp_engine.collateral(collateral.collateral_type, other_address)
        assert Wad(other_balance_before) + amount == Wad(other_balance_after)

        # teardown
        cleanup_urn(geb, collateral, our_address)

    def test_move(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        collateral.approve(our_address)
        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        wrap_eth(geb, our_address, Wad(10))
        assert collateral.adapter.join(our_address, Wad(3)).transact()
        assert geb.cdp_engine.frob(collateral.collateral_type, our_address, Wad(3), Wad(10)).transact()
        other_balance_before = geb.cdp_engine.coin_balance(other_address)

        # when
        assert geb.cdp_engine.move(our_address, other_address, Rad(Wad(10))).transact()

        # then
        other_balance_after = geb.cdp_engine.coin_balance(other_address)
        assert other_balance_before + Rad(Wad(10)) == other_balance_after

        # rollback
        cleanup_urn(geb, collateral, our_address)

    def test_fork(self, geb, our_address, other_address):
        # given
        collateral = geb.collaterals['ETH-A']
        geb.cdp_engine.hope(our_address).transact(from_address=other_address)
        geb.cdp_engine.hope(other_address).transact(from_address=our_address)

        our_urn = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
        wrap_eth(geb, our_address, Wad(6))
        assert collateral.adapter.join(our_address, Wad(6)).transact()
        assert geb.cdp_engine.frob(collateral.collateral_type, our_address, Wad(6), Wad(20)).transact()
        urn_before = geb.cdp_engine.cdp(collateral.collateral_type, other_address)

        # when
        assert geb.cdp_engine.fork(collateral.collateral_type, our_address, other_address, Wad(3), Wad(10)).transact()

        # then
        urn_after = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert urn_before.ink + Wad(3) == urn_after.ink
        assert urn_before.art + Wad(10) == urn_after.art

        # rollback
        cleanup_urn(geb, collateral, our_address)


class TestCat:
    def test_getters(self, geb):
        assert isinstance(geb.liquidation_engine.contract_enabled(), bool)
        assert isinstance(geb.liquidation_engine.cdp_engine, CDPEngine)
        assert isinstance(geb.liquidation_engine.accounting_engine, AccountingEngine)

        collateral = geb.collaterals['ETH-C']
        assert geb.liquidation_engine.flipper(collateral.collateral_type) == collateral.collateral_auction_house.address
        assert isinstance(geb.liquidation_engine.collateral_to_sell(collateral.collateral_type), Wad)
        assert isinstance(geb.liquidation_engine.liquidation_penalty(collateral.collateral_type), Ray)


class TestSpotter:
    def test_mat(self, geb):
        val = Ray(geb.collaterals['ETH-A'].pip.read_as_int())

        collateral_type = geb.cdp_engine.collateral_type('ETH-A')
        redemption_price = geb.oracle_relayer.redemption_price()
        mat = geb.oracle_relayer.safety_c_ratio(collateral_type)

        assert mat == (Ray(val * 10 ** 9) / redemption_price) / (collateral_type.spot)


class TestAccountingEngine:
    def test_getters(self, geb):
        assert isinstance(geb.acct_engine.cdp_engine, CDPEngine)
        assert isinstance(geb.acct_engine.contract_enabled(), bool)
        assert isinstance(geb.acct_engine.surplus_auction_house, Address)
        assert isinstance(geb.acct_engine.debt_auction_house(), Address)
        assert isinstance(geb.acct_engine.debt_queue(), Rad)
        assert isinstance(geb.acct_engine.sin_of(0), Rad)
        assert isinstance(geb.acct_engine.total_on_auction_debt(), Rad)
        assert isinstance(geb.acct_engine.woe(), Rad)
        assert isinstance(geb.acct_engine.pop_debt_delay(), int)
        assert isinstance(geb.acct_engine.initial_debt_auction_minted_tokens(), Wad)
        assert isinstance(geb.acct_engine.debt_auction_bid_size(), Rad)
        assert isinstance(geb.acct_engine.surplus_auction_amount_to_sell(), Rad)
        assert isinstance(geb.acct_engine.surplus_buffer(), Rad)

    def test_empty_flog(self, geb):
        assert geb.acct_engine.flog(0).transact()

    def test_settle_debt(self, geb):
        assert geb.acct_engine.settle_debt(Rad(0)).transact()

    def test_cancel_auctioned_debt_with_surplus(self, geb):
        assert geb.acct_engine.cancel_auctioned_debt_with_surplus(Rad(0)).transact()


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


class TestCoinSavingsAccount:
    def test_getters(self, geb):
        assert isinstance(geb.coin_savings_acct.savings(), Wad)
        assert isinstance(geb.coin_savings_acct.savings_rate(), Ray)
        assert isinstance(geb.coin_savings_acct.update_time(), datetime)

        assert geb.pot.savings() >= Wad(0)
        assert geb.pot.savings_rate() > Ray(0)
        assert datetime.fromtimestamp(0) < geb.coin_savings_acct.update_time() < datetime.utcnow()

    def test_tax_single(self, geb):
        assert geb.pot.tax_single().transact()


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
        TestVat.ensure_clean_cdp(geb, collateral, our_address)
        initial_dai = geb.cdp_engine.coin_balance(our_address)
        wrap_eth(geb, our_address, Wad.from_number(9))

        # Ensure our collateral enters the urn
        collateral_balance_before = collateral.gem.balance_of(our_address)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, Wad.from_number(9)).transact()
        assert collateral.gem.balance_of(our_address) == collateral_balance_before - Wad.from_number(9)

        # Add collateral without generating Dai
        frob(geb, collateral, our_address, dink=Wad.from_number(3), dart=Wad(0))
        print(f"After adding collateral:         {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).ink == Wad.from_number(3)
        assert geb.cdp_engine.cdp(collateral_type, our_address).art == Wad(0)
        assert geb.cdp_engine.collateral(collateral_type, our_address) == Wad.from_number(9) - geb.cdp_engine.cdp(collateral_type, our_address).ink
        assert geb.cdp_engine.coin_balance(our_address) == initial_dai

        # Generate some Dai
        frob(geb, collateral, our_address, dink=Wad(0), dart=Wad.from_number(153))
        print(f"After generating dai:            {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).ink == Wad.from_number(3)
        assert geb.cdp_engine.cdp(collateral_type, our_address).art == Wad.from_number(153)
        assert geb.cdp_engine.coin_balance(our_address) == initial_dai + Rad.from_number(153)

        # Add collateral and generate some more Dai
        frob(geb, collateral, our_address, dink=Wad.from_number(6), dart=Wad.from_number(180))
        print(f"After adding collateral and dai: {geb.cdp_engine.cdp(collateral_type, our_address)}")
        assert geb.cdp_engine.cdp(collateral_type, our_address).ink == Wad.from_number(9)
        assert geb.cdp_engine.collateral(collateral_type, our_address) == Wad(0)
        assert geb.cdp_engine.cdp(collateral_type, our_address).art == Wad.from_number(333)
        assert geb.cdp_engine.coin_balance(our_address) == initial_dai + Rad.from_number(333)

        # Mint and withdraw our Dai
        dai_balance_before = geb.dai.balance_of(our_address)
        geb.approve_dai(our_address)
        assert isinstance(geb.dai_adapter, DaiJoin)
        assert geb.dai_adapter.exit(our_address, Wad.from_number(333)).transact()
        assert geb.dai.balance_of(our_address) == dai_balance_before + Wad.from_number(333)
        assert geb.cdp_engine.coin_balance(our_address) == initial_dai
        assert geb.cdp_engine.debt() >= initial_dai + Rad.from_number(333)

        # Repay (and burn) our Dai
        assert geb.dai_adapter.join(our_address, Wad.from_number(333)).transact()
        assert geb.dai.balance_of(our_address) == Wad(0)
        assert geb.cdp_engine.coin_balance(our_address) == initial_dai + Rad.from_number(333)

        # Withdraw our collateral
        frob(geb, collateral, our_address, dink=Wad(0), dart=Wad.from_number(-333))
        frob(geb, collateral, our_address, dink=Wad.from_number(-9), dart=Wad(0))
        assert geb.cdp_engine.collateral(collateral_type, our_address) == Wad.from_number(9)
        assert collateral.adapter.exit(our_address, Wad.from_number(9)).transact()
        collateral_balance_after = collateral.gem.balance_of(our_address)
        assert collateral_balance_before == collateral_balance_after

        # Cleanup
        cleanup_urn(geb, collateral, our_address)
