# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 reverendus, bargst, EdNoepel
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
from datetime import datetime
from web3 import Web3

from pyflex import Address
from pyflex.approval import directly, approve_cdp_modification_directly
from pyflex.auctions import AuctionContract, CollateralAuctionHouse, SurplusAuctionHouse, DebtAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, CDP
from pyflex.numeric import Wad, Ray, Rad
from tests.test_gf import wrap_eth, mint_gov, set_collateral_price, wait, wrap_modify_CDP_collateralization
from tests.test_gf import cleanup_cdp, max_delta_debt, simulate_bite


def create_surplus(geb: GfDeployment, surplus_auction_house: SurplusAuctionHouse, deployment_address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(surplus_auction_house, SurplusAuctionHouse)
    assert isinstance(deployment_address, Address)

    joy = geb.cdp_engine.dai(geb.accounting_engine.address)

    if joy < geb.accounting_engine.hump() + geb.accounting_engine.bump():
        # Create a CDP with surplus
        print('Creating a CDP with surplus')
        collateral = geb.collaterals['ETH-B']
        assert surplus_auction_house.auctions_started() == 0
        wrap_eth(geb, deployment_address, Wad.from_number(0.1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(0.1)).transact(
            from_address=deployment_address)
        frob(geb, collateral, deployment_address, dink=Wad.from_number(0.1), dart=Wad.from_number(10))
        assert geb.jug.drip(collateral.collateral_type).transact(from_address=deployment_address)
        joy = geb.cdp_engine.dai(geb.accounting_engine.address)
        assert joy >= geb.accounting_engine.hump() + geb.accounting_engine.bump()
    else:
        print(f'Surplus of {joy} already exists; skipping CDP creation')


def create_debt(web3: Web3, geb: GfDeployment, our_address: Address, deployment_address: Address):
    assert isinstance(web3, Web3)
    assert isinstance(geb, GfDeployment)
    assert isinstance(our_address, Address)
    assert isinstance(deployment_address, Address)

    # Create a CDP
    collateral = geb.collaterals['ETH-A']
    collateral_type = collateral.collateral_type
    wrap_eth(geb, deployment_address, Wad.from_number(1))
    collateral.approve(deployment_address)
    assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
        from_address=deployment_address)
    frob(geb, collateral, deployment_address, dink=Wad.from_number(1), dart=Wad(0))
    dart = max_dart(geb, collateral, deployment_address) - Wad(1)
    frob(geb, collateral, deployment_address, dink=Wad(0), dart=dart)

    # Undercollateralize and bite the CDP
    to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)
    set_collateral_price(geb, collateral, to_price)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
    collateral_type = geb.cdp_engine.collateral_type(collateral_type.name)
    safe = Ray(cdp.art) * geb.cdp_engine.collateral_type(collateral_type.name).rate <= Ray(cdp.ink) * collateral_type.spot
    assert not safe
    simulate_bite(geb, collateral, deployment_address)
    assert geb.cat.bite(collateral.collateral_type, Urn(deployment_address)).transact()
    flip_kick = collateral.collateral_auction_house.auctions_started()

    # Generate some Dai, bid on and win the flip auction without covering all the debt
    wrap_eth(geb, our_address, Wad.from_number(10))
    collateral.approve(our_address)
    assert collateral.adapter.join(our_address, Wad.from_number(10)).transact(from_address=our_address)
    web3.eth.defaultAccount = our_address.address
    frob(geb, collateral, our_address, dink=Wad.from_number(10), dart=Wad.from_number(200))
    collateral.collateral_auction_house.approve(geb.cdp_engine.address, approval_function=hope_directly())
    current_bid = collateral.collateral_auction_house.bids(flip_kick)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
    assert Rad(cdp.art) > current_bid.tab
    bid = Rad.from_number(6)
    TestCollateralAuctionHouse.tend(collateral.collateral_auction_house, flip_kick, our_address, current_bid.lot, bid)
    geb.cdp_engine.can(our_address, collateral.collateral_auction_house.address)
    wait(geb, our_address, collateral.collateral_auction_house.ttl()+1)
    assert collateral.collateral_auction_house.deal(flip_kick).transact()

    # Raise debt from the queue (note that vow.wait is 0 on our testchain)
    bites = geb.cat.past_bites(100)
    for bite in bites:
        era_bite = bite.era(web3)
        assert era_bite > int(datetime.now().timestamp()) - 120
        assert geb.accounting_engine.debt_balance_of(era_bite) > Rad(0)
        assert geb.accounting_engine.flog(era_bite).transact()
        assert geb.accounting_engine.debt_balance_of(era_bite) == Rad(0)
    # Cancel out surplus and debt
    dai_vow = geb.cdp_engine.dai(geb.accounting_engine.address)
    assert dai_vow <= geb.accounting_engine.woe()
    assert geb.accounting_engine.heal(dai_vow).transact()
    assert geb.accounting_engine.woe() >= geb.accounting_engine.sump()


def check_active_auctions(auction: AuctionContract):
    for bid in auction.active_auctions():
        assert bid.id > 0
        assert auction.auctions_started() >= bid.id
        assert isinstance(bid.high_bidder, Address)
        assert bid.high_bidder != Address("0x0000000000000000000000000000000000000000")


class TestCollateralAuctionHouse:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def collateral_auction_house(self, collateral, deployment_address) -> CollateralAuctionHouse:
        return collateral.collateral_auction_house

    @staticmethod
    def tend(collateral_auction_house: CollateralAuctionHouse, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(collateral_auction_house, CollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert lot == current_bid.lot
        assert bid <= current_bid.tab
        assert bid > current_bid.bid
        assert (bid >= Rad(collateral_auction_house.bid_increase()) * current_bid.bid) or (bid == current_bid.tab)

        assert collateral_auction_house.tend(id, lot, bid).transact(from_address=address)

    @staticmethod
    def dent(collateral_auction_house: CollateralAuctionHouse, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(collateral_auction_house, CollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert bid == current_bid.bid
        assert bid == current_bid.tab
        assert lot < current_bid.lot
        assert collateral_auction_house.bid_increase() * lot <= current_bid.lot

        assert collateral_auction_house.dent(id, lot, bid).transact(from_address=address)

    def test_getters(self, geb, collateral_auction_house):
        assert collateral_auction_house.cdp_engine() == geb.cdp_engine.address
        assert collateral_auction_house.bid_increase() > Wad.from_number(1)
        assert collateral_auction_house.ttl() > 0
        assert collateral_auction_house.tau() > collateral_auction_house.ttl()
        assert collateral_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, collateral, collateral_auction_house, our_address, other_address, deployment_address):
        # Create a CDP
        collateral = geb.collaterals['ETH-A']
        auctions_started_before = collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
        frob(geb, collateral, deployment_address, dink=Wad.from_number(1), dart=Wad(0))
        dart = max_dart(geb, collateral, deployment_address) - Wad(1)
        frob(geb, collateral, deployment_address, dink=Wad(0), dart=dart)

        # Mint and withdraw all the Dai
        geb.approve_dai(deployment_address)
        assert geb.dai_adapter.exit(deployment_address, dart).transact(from_address=deployment_address)
        assert geb.dai.balance_of(deployment_address) == dart
        assert geb.cdp_engine.dai(deployment_address) == Rad(0)

        # Undercollateralize the CDP
        to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        collateral_type = geb.cdp_engine.collateral_type(collateral_type.name)
        assert collateral_type.rate is not None
        assert collateral_type.spot is not None
        safe = Ray(cdp.art) * geb.cdp_engine.collateral_type(collateral_type.name).rate <= Ray(cdp.ink) * collateral_type.spot
        assert not safe
        assert len(collateral_auction_house.active_auctions()) == 0

        # Bite the CDP, which moves debt to the vow and auctions_started the collateral_auction_house
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        assert cdp.ink > Wad(0)
        lot = min(cdp.ink, geb.cat.lump(collateral_type))  # Wad
        art = min(cdp.art, (lot * cdp.art) / cdp.ink)  # Wad
        tab = art * collateral_type.rate  # Wad
        assert tab == dart
        simulate_bite(geb, collateral, deployment_address)
        assert geb.cat.bite(collateral.collateral_type, Urn(deployment_address)).transact()
        kick = collateral_auction_house.auctions_started()
        assert kick == auctions_started_before + 1
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        # Check cdp_engine, accounting_engine, and liquidation_engine
        assert cdp.ink == Wad(0)
        assert cdp.art == dart - art
        assert geb.cdp_engine.global_unbacked_debt() > Rad(0)
        assert geb.accounting_engine.debt_balance() == Rad(tab)
        bites = geb.cat.past_bites(1)
        assert len(bites) == 1
        last_bite = bites[0]
        assert last_bite.tab > Rad(0)
        # Check the collateral_auction_house
        current_bid = collateral_auction_house.bids(kick)
        assert isinstance(current_bid, CollateralAuctionHouse.Bid)
        assert current_bid.lot > Wad(0)
        assert current_bid.tab > Rad(0)
        assert current_bid.bid == Rad(0)
        # Cat doesn't incorporate the liquidation penalty (chop), but the kicker includes it.
        # Awaiting word from @dc why this is so.
        #assert last_bite.tab == current_bid.tab
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, CollateralAuctionHouse.KickLog)
        assert log.id == kick
        assert log.lot == current_bid.lot
        assert log.bid == current_bid.bid
        assert log.tab == current_bid.tab
        assert log.usr == deployment_address
        assert log.gal == geb.accounting_engine.address

        # Wrap some eth and handle approvals before bidding
        eth_required = Wad(current_bid.tab / Rad(collateral_type.spot)) * Wad.from_number(1.1)
        wrap_eth(geb, other_address, eth_required)
        collateral.approve(other_address)
        assert collateral.adapter.join(other_address, eth_required).transact(from_address=other_address)
        wrap_eth(geb, our_address, eth_required)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, eth_required).transact(from_address=our_address)

        # Test the _tend_ phase of the auction
        collateral_auction_house.approve(geb.cdp_engine.address, approval_function=hope_directly(from_address=other_address))
        # Add Wad(1) to counter precision error converting tab from Rad to Wad
        frob(geb, collateral, other_address, dink=eth_required, dart=Wad(current_bid.tab) + Wad(1))
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert Rad(cdp.art) >= current_bid.tab
        # Bid the tab to instantly transition to dent stage
        TestCollateralAuctionHouse.tend(collateral_auction_house, kick, other_address, current_bid.lot, current_bid.tab)
        current_bid = collateral_auction_house.bids(kick)
        assert current_bid.high_bidder == other_address
        assert current_bid.bid == current_bid.tab
        assert len(collateral_auction_house.active_auctions()) == 1
        check_active_auctions(collateral_auction_house)
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, CollateralAuctionHouse.TendLog)
        assert log.high_bidder == current_bid.guy
        assert log.id == current_bid.id
        assert log.lot == current_bid.lot
        assert log.bid == current_bid.bid

        # Test the _dent_ phase of the auction
        collateral_auction_house.approve(geb.cdp_engine.address, approval_function=hope_directly(from_address=our_address))
        frob(geb, collateral, our_address, dink=eth_required, dart=Wad(current_bid.tab) + Wad(1))
        lot = current_bid.lot - Wad.from_number(0.2)
        assert collateral_auction_house.bid_increase() * lot <= current_bid.lot
        assert geb.cdp_engine.can(our_address, collateral_auction_house.address)
        TestCollateralAuctionHouse.dent(collateral_auction_house, kick, our_address, lot, current_bid.tab)
        current_bid = collateral_auction_house.bids(kick)
        assert current_bid.high_bidder == our_address
        assert current_bid.bid == current_bid.tab
        assert current_bid.lot == lot
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, CollateralAuctionHouse.DentLog)
        assert log.high_bidder == current_bid.guy
        assert log.id == current_bid.id
        assert log.lot == current_bid.lot
        assert log.bid == current_bid.bid

        # Exercise _deal_ after bid has expired
        wait(geb, our_address, collateral_auction_house.ttl()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.tic < now or current_bid.end < now
        assert collateral_auction_house.deal(kick).transact(from_address=our_address)
        assert len(collateral_auction_house.active_auctions()) == 0
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, CollateralAuctionHouse.DealLog)
        assert log.usr == our_address

        # Grab our collateral
        collateral_before = collateral.gem.balance_of(our_address)
        assert collateral.adapter.exit(our_address, current_bid.lot).transact(from_address=our_address)
        collateral_after = collateral.gem.balance_of(our_address)
        assert collateral_before < collateral_after

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_cdp(geb, collateral, other_address)


class TestSurplusAuctionHouse:
    @pytest.fixture(scope="session")
    def surplus_auction_house(self, geb: GfDeployment) -> SurplusAuctionHouse:
        return geb.surplus_auction_house

    @staticmethod
    def tend(surplus_auction_house: SurplusAuctionHouse, id: int, address: Address, lot: Rad, bid: Wad):
        assert (isinstance(surplus_auction_house, SurplusAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(lot, Rad))
        assert (isinstance(bid, Wad))

        assert surplus_auction_house.contract_enabled() == 1

        current_bid = surplus_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert lot == current_bid.lot
        assert bid > current_bid.bid
        assert bid >= surplus_auction_house.bid_increase() * current_bid.bid

        assert surplus_auction_house.tend(id, lot, bid).transact(from_address=address)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.TendLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.lot == lot
        assert log.bid == bid

    def test_getters(self, geb, surplus_auction_house):
        assert surplus_auction_house.vat() == geb.cdp_engine.address
        assert surplus_auction_house.bid_increase() > Wad.from_number(1)
        assert surplus_auction_house.ttl() > 0
        assert surplus_auction_house.tau() > surplus_auction_house.ttl()
        assert surplus_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, surplus_auction_house, our_address, other_address, deployment_address):
        create_surplus(geb, surplus_auction_house, deployment_address)

        joy_before = geb.cdp_engine.dai(geb.accounting_engine.address)
        # total surplus > total debt + surplus auction lot size + surplus buffer
        assert joy_before > geb.cdp_engine.debt_balance(geb.accounting_engine.address) + geb.accounting_engine.bump() + geb.accounting_engine.hump()
        assert (geb.cdp_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.sin()) - geb.accounting_engine.ash() == Rad(0)
        assert geb.accounting_engine.flap().transact()
        kick = surplus_auction_house.auctions_started()
        assert kick == 1
        assert len(surplus_auction_house.active_auctions()) == 1
        check_active_auctions(surplus_auction_house)
        current_bid = surplus_auction_house.bids(1)
        assert current_bid.lot > Rad(0)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.KickLog)
        assert log.id == kick
        assert log.lot == current_bid.lot
        assert log.bid == current_bid.bid

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, surplus_auction_house.tau()+1)
        assert surplus_auction_house.tick(kick).transact()

        # Bid on the resurrected auction
        mint_gov(geb.gov, our_address, Wad.from_number(10))
        surplus_auction_house.approve(geb.gov.address, directly(from_address=our_address))
        bid = Wad.from_number(0.001)
        assert geb.gov.balance_of(our_address) > bid
        TestSurplusAuctionHouse.tend(surplus_auction_house, kick, our_address, current_bid.lot, bid)
        current_bid = surplus_auction_house.bids(kick)
        assert current_bid.bid == bid
        assert current_bid.high_bidder == our_address

        # Exercise _deal_ after bid has expired
        wait(geb, our_address, surplus_auction_house.ttl()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.tic < now or current_bid.end < now
        assert surplus_auction_house.deal(kick).transact(from_address=our_address)
        joy_after = geb.cdp_engine.dai(geb.accounting_engine.address)
        print(f'joy_before={str(joy_before)}, joy_after={str(joy_after)}')
        assert joy_before - joy_after == geb.accounting_engine.bump()
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.DealLog)
        assert log.usr == our_address
        assert log.id == kick

        # Grab our dai
        geb.approve_dai(our_address)
        assert geb.dai_adapter.exit(our_address, Wad(current_bid.lot)).transact(from_address=our_address)
        assert geb.dai.balance_of(our_address) >= Wad(current_bid.lot)
        assert (geb.cdp_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.sin()) - geb.accounting_engine.ash() == Rad(0)


class TestDebtAuctionHouse:
    @pytest.fixture(scope="session")
    def debt_auction_house(self, geb: GfDeployment) -> DebtAuctionHouse:
        return geb.debt_auction_house

    @staticmethod
    def dent(debt_auction_house: DebtAuctionHouse, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(debt_auction_house, DebtAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        assert debt_auction_house.contract_enabled() == 1

        current_bid = debt_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert bid == current_bid.bid
        assert Wad(0) < lot < current_bid.lot
        assert debt_auction_house.bid_decerase() * lot <= current_bid.lot

        assert debt_auction_house.dent(id, lot, bid).transact(from_address=address)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.DentLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.lot == lot
        assert log.bid == bid

    def test_getters(self, geb, debt_auction_house):
        assert debt_auction_house.cdp_engine() == geb.cdp_engine.address
        assert debt_auction_house.bid_decrease() > Wad.from_number(1)
        assert debt_auction_house.ttl() > 0
        assert debt_auction_house.tau() > debt_auction_house.ttl()
        assert debt_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, debt_auction_house, our_address, other_address, deployment_address):
        create_debt(web3, geb, our_address, deployment_address)

        # Kick off the flop auction
        assert debt_auction_house.auctions_started() == 0
        assert len(debt_auction_house.active_auctions()) == 0
        assert geb.cdp_engine.dai(geb.accounting_engine.address) == Rad(0)
        assert geb.accounting_engine.flop().transact()
        kick = debt_auction_house.auctions_started()
        assert kick == 1
        assert len(debt_auction_house.active_auctions()) == 1
        check_active_auctions(debt_auction_house)
        current_bid = debt_auction_house.bids(kick)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.KickLog)
        assert log.id == kick
        assert log.lot == current_bid.lot
        assert log.bid == current_bid.bid
        assert log.gal == geb.accounting_engine.address

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, debt_auction_house.tau()+1)
        assert debt_auction_house.tick(kick).transact()
        assert debt_auction_house.bids(kick).lot == current_bid.lot * debt_auction_house.pad()

        # Bid on the resurrected auction
        bid = Wad.from_number(0.000005)
        debt_auction_house.approve(geb.cdp_engine.address, hope_directly())
        assert geb.cdp_engine.can(our_address, debt_auction_house.address)
        TestDebtAuctionHouse.dent(debt_auction_house, kick, our_address, bid, current_bid.bid)
        current_bid = debt_auction_house.bids(kick)
        assert current_bid.high_bidder == our_address

        # Confirm victory
        wait(geb, our_address, debt_auction_house.ttl()+1)
        assert debt_auction_house.contract_enabled()
        now = int(datetime.now().timestamp())
        assert (current_bid.tic < now and current_bid.tic != 0) or current_bid.end < now
        gov_before = geb.gov.balance_of(our_address)
        assert debt_auction_house.deal(kick).transact(from_address=our_address)
        gov_after = geb.gov.balance_of(our_address)
        assert gov_after > gov_before
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.DealLog)
        assert log.usr == our_address
        assert log.id == kick
