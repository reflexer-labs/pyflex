# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel
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


import pytest
from datetime import datetime, timedelta

from pyflex import Address
from pyflex.approval import directly, approve_cdp_modification_directly
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral
from pyflex.numeric import Wad, Ray, Rad
from pyflex.shutdown import ShutdownModule, GlobalSettlement

from tests.helpers import time_travel_by
from tests.test_auctions import create_surplus
from tests.test_gf import mint_gov, wrap_eth, wrap_modify_cdp_collateralization


def open_cdp(geb: GfDeployment, collateral: Collateral, address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)

    collateral.approve(address)
    wrap_eth(geb, address, Wad.from_number(10))
    assert collateral.adapter.join(address, Wad.from_number(10)).transact(from_address=address)
    wrap_modify_cdp_collateralization(geb, collateral, address, Wad.from_number(10), Wad.from_number(15))

    assert geb.cdp_engine.global_debt() >= Rad(Wad.from_number(15))
    assert geb.cdp_engine.coin_balance(address) >= Rad.from_number(10)


def create_surplus_auction(geb: GfDeployment, deployment_address: Address, our_address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(deployment_address, Address)
    assert isinstance(our_address, Address)

    surplus_auction_house = geb.surplus_auction_house
    create_surplus(geb, surplus_auction_house, deployment_address)
    coin_balance = geb.cdp_engine.coin_balance(geb.accounting_engine.address)
    assert coin_balance > geb.cdp_engine.debt_balance(geb.accounting_engine.address) + geb.accounting_engine.surplus_auction_amount_to_sell() + geb.accounting_engine.surplus_buffer()
    assert (geb.cdp_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - geb.accounting_engine.total_on_auction_debt() == Rad(0)
    assert geb.accounting_engine.auction_surplus().transact()

    mint_gov(geb.gov, our_address, Wad.from_number(10))
    surplus_auction_house.approve(geb.gov.address, directly(from_address=our_address))
    bid = Wad.from_number(0.001)
    assert geb.gov.balance_of(our_address) > bid
    assert surplus_auction_house.increase_bid_size(surplus_auction_house.auctions_started(), geb.accounting_engine.surplus_auction_amount_to_sell(), bid).transact(from_address=our_address)


nobody = Address("0x0000000000000000000000000000000000000000")

class TestShutdownModule:
    """This test must be run after other GEB tests because it will leave the testchain `disabled`d."""

    def test_init(self, geb, deployment_address, our_address):
        assert geb.esm is not None
        assert isinstance(geb.esm, ShutdownModule)
        assert isinstance(geb.esm.address, Address)
        assert geb.esm.trigger_threshold() > Wad(0)
        assert not geb.esm.settled()

        coin_balance = geb.cdp_engine.coin_balance(geb.accounting_engine.address)
        awe = geb.cdp_engine.debt_balance(geb.accounting_engine.address)
        # If `test_shutdown.py` is run in isolation, create a surplus auction to exercise `terminate_auction_prematurely`
        if coin_balance == Rad(0) and awe == Rad(0):
            create_surplus_auction(geb, deployment_address, our_address)

    def _test_burn_tokens(self, geb, our_address):
        assert geb.gov.approve(geb.esm.address).transact()

        # This should have no effect yet succeed regardless
        assert geb.esm.burn_tokens(Wad(0)).transact()
        assert geb.esm.total_amount_burnt() == Wad(0)
        assert geb.esm.burnt_tokens(our_address) == Wad(0)

        # Ensure the appropriate amount of MKR can be burn_tokensed
        mint_gov(geb.gov, our_address, geb.esm.min())
        assert geb.esm.burn_tokens(geb.esm.min()).transact()
        assert geb.esm.total_amount_burnt() == geb.esm.min()

        # Joining extra MKR should succeed yet have no effect
        mint_gov(geb.gov, our_address, Wad(1))
        assert geb.esm.burn_tokens(Wad(153)).transact()
        assert geb.esm.total_amount_burnt() == geb.esm.trigger_threshold() + Wad(153)
        assert geb.esm.burnt_tokens(our_address) == geb.esm.total_amount_burnt()

    def test_shutdown(self, geb, our_address):
        open_cdp(geb, geb.collaterals['ETH-A'], our_address)

        mint_gov(geb.gov, our_address, geb.esm.trigger_threshold()*2)
        print(geb.gov.balance_of(our_address))
        import sys

        assert geb.global_settlement.contract_enabled()
        assert not geb.esm.settled()
        assert geb.esm.shutdown().transact()

        assert geb.esm.settled()
        assert not geb.global_settlement.contract_enabled()

class TestGlobalSettlement:
    """This test must be run after TestShutdownModule, which calls `esm.shutdown`."""

    def test_init(self, geb):
        assert geb.global_settlement is not None
        assert isinstance(geb.global_settlement, GlobalSettlement)
        assert isinstance(geb.esm.address, Address)

    def test_getters(self, geb):
        assert not geb.global_settlement.contract_enabled()
        assert datetime.utcnow() - timedelta(minutes=5) < geb.global_settlement.when() < datetime.utcnow()
        assert geb.global_settlement.shutdown_cooldown() >= 0
        assert geb.global_settlement.outstanding_coin_supply() >= Rad(0)

        for collateral in geb.collaterals.values():
            collateral_type = collateral.collateral_type
            assert geb.global_settlement.final_coin_per_collateral_price(collateral_type) == Ray(0)
            assert geb.global_settlement.collateral_shortfall(collateral_type) == Wad(0)
            assert geb.global_settlement.art(collateral_type) == Wad(0)
            assert geb.global_settlement.collatera_cash_price(collateral_type) == Ray(0)

    def test_disable_contract(self, geb):
        collateral = geb.collaterals['ETH-A']
        collateral_type = collateral.collateral_type

        assert geb.global_settlement.shutdown_system(collateral_type).transact()
        assert geb.global_settlement.collateral_total_debt(collateral_type) > Wad(0)
        assert geb.global_settlement.final_coin_per_collateral_price(collateral_type) > Ray(0)

    def test_terminate_auction_prematurely(self, geb):
        last_surplus_auction = geb.surplus_auction_house.bids(geb.surplus_auction_house.auctions_started())
        last_collateral_auction = geb.debt_auction_house.bids(geb.debt_auction_house.auctions_started())
        if last_surplus_auction.auction_deadline > 0 and last_surplus_auction.high_bidder is not nobody:
            auction = geb.surplus_auction_house
        elif last_collateral_auction.auction_deadline > 0 and last_collatera_auction.high_bidder is not nobody:
            auction = geb.debt_auction_house
        else:
            auction = None

        if auction:
            print(f"active {auction} auction: {auction.bids(auction.auctions_started())}")
            assert not auction.contract_enabled()
            kick = auction.auctions_started()
            assert auction.terminate_auction_prematurely(kick).transact()
            assert auction.bids(kick).high_bidder == nobody

    def test_process_cdp(self, geb, our_address):
        collateral_type = geb.collaterals['ETH-A'].collateral_type

        cdp = geb.cdp_engine.cdp(collateral_type, our_address)
        owe = Ray(cdp.generated_debt) * geb.cdp_engine.collateral_type(collateral_type.name).accumulated_rates * geb.global_settlement.final_coin_per_collateral_price(collateral_type)
        assert owe > Ray(0)
        wad = min(Ray(cdp.locked_collateral), owe)
        print(f"owe={owe} wad={wad}")

        assert geb.global_settlement.process_cdp(collateral_type, our_address).transact()
        assert geb.cdp_engine.cdp(collateral_type, our_address).generated_debt == Wad(0)
        assert geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral > Wad(0)
        assert geb.cdp_engine.debt_balance(geb.accounting_engine.address) > Rad(0)

        assert geb.cdp_engine.global_debt() > Rad(0)
        assert geb.cdp_engine.global_unbacked_debt() > Rad(0)

    def test_close_cdp(self, web3, geb, our_address):
        collateral = geb.collaterals['ETH-A']
        collateral_type = collateral.collateral_type

        assert geb.global_settlement.free_collateral(collateral_type).transact()
        assert geb.cdp_engine.cdp(collateral_type, our_address).locked_collateral == Wad(0)
        assert geb.cdp_engine.token_collateral(collateral_type, our_address) > Wad(0)
        assert collateral.adapter.exit(our_address, geb.cdp_engine.token_collateral(collateral_type, our_address)).transact()

        assert geb.global_settlement.shutdown_cooldown() == 5
        time_travel_by(web3, 5)
        assert geb.global_settlement.set_outstanding_coin_supply().transact()
        assert geb.global_settlement.calculate_cash_price(collateral_type).transact()
        assert geb.global_settlement.collateral_cash_price(collateral_type) > Ray(0)

    @pytest.mark.skip(reason="unable to add system_coin to the `coin_bag`")
    def test_prepare_coins_for_rdeeming(self, geb, our_address):
        assert geb.global_settlement.coin_bag(our_address) == Wad(0)
        assert geb.global_settlement.outstanding_coin_supply() > Rad(0)
        assert geb.system_coin.approve(geb.global_settlement.address).transact()
        assert geb.cdp_engine.coin_balance(our_address) >= Rad.from_number(10)
        # FIXME: `pack` fails, possibly because we're passing 0 to `cdpEngine.transfer_collateral`
        assert geb.global_settlement.prepare_coins_for_redeeming(Wad.from_number(10)).transact()
        assert geb.global_settlement.coin_bag(our_address) == Wad.from_number(10)
