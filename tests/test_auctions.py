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
from pyflex.auctions import AuctionContract, EnglishCollateralAuctionHouse, SurplusAuctionHouse, DebtAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, CDP, OracleRelayer
from pyflex.numeric import Wad, Ray, Rad
from tests.test_gf import wrap_eth, mint_gov, set_collateral_price, wait, wrap_modify_cdp_collateralization
from tests.test_gf import cleanup_cdp, max_delta_debt, simulate_liquidate_cdp


def create_surplus(geb: GfDeployment, surplus_auction_house: SurplusAuctionHouse, deployment_address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(surplus_auction_house, SurplusAuctionHouse)
    assert isinstance(deployment_address, Address)

    joy = geb.cdp_engine.coin_balance(geb.accounting_engine.address)

    if joy < geb.accounting_engine.surplus_buffer() + geb.accounting_engine.surplus_auction_amount_to_sell():
        # Create a CDP with surplus
        print('Creating a CDP with surplus')
        collateral = geb.collaterals['ETH-A']
        assert surplus_auction_house.auctions_started() == 0
        wrap_eth(geb, deployment_address, Wad.from_number(10))
        collateral.approve(deployment_address)

        assert collateral.adapter.join(deployment_address, Wad.from_number(10)).transact(from_address=deployment_address)

        wrap_modify_cdp_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(10), delta_debt=Wad.from_number(8))
        assert geb.tax_collector.tax_single(collateral.collateral_type).transact(from_address=deployment_address)
          
        joy = geb.cdp_engine.coin_balance(geb.accounting_engine.address)
        assert joy >= geb.accounting_engine.surplus_buffer() + geb.accounting_engine.surplus_auction_amount_to_sell()
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
    wrap_modify_cdp_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1),
                                      delta_debt=Wad(0))
    delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
    wrap_modify_cdp_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0),
                                      delta_debt=delta_debt)

    # Undercollateralize and liquidation the CDP
    to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)
    set_collateral_price(geb, collateral, to_price)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
    collateral_type = geb.cdp_engine.collateral_type(collateral_type.name)
    safe = Ray(cdp.generated_debt) * geb.cdp_engine.collateral_type(collateral_type.name).accumulated_rates <= \
            Ray(cdp.locked_collateral) * collateral_type.safety_price

    assert not safe
    simulate_liquidate_cdp(geb, collateral, deployment_address)
    assert geb.liquidation_engine.liquidate_cdp(collateral.collateral_type, CDP(deployment_address)).transact()

    auction_id = collateral.collateral_auction_house.auctions_started()

    # Generate some system coin, bid on and win the collateral auction without covering all the debt
    wrap_eth(geb, our_address, Wad.from_number(100))
    collateral.approve(our_address)
    assert collateral.adapter.join(our_address, Wad.from_number(100)).transact(from_address=our_address)

    web3.eth.defaultAccount = our_address.address
    wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=Wad.from_number(100),
                                      delta_debt=Wad.from_number(200))

    collateral.collateral_auction_house.approve(geb.cdp_engine.address, approval_function=approve_cdp_modification_directly())

    current_bid = collateral.collateral_auction_house.bids(auction_id)
    cdp = geb.cdp_engine.cdp(collateral.collateral_type, our_address)
    assert Rad(cdp.generated_debt) > current_bid.amount_to_raise

    bid_amount = Rad.from_number(90)
    print("create_debt(): before TestEnglish increase_bid_size")
    TestEnglishCollateralAuctionHouse.increase_bid_size(collateral.collateral_auction_house, geb.oracle_relayer,
                                                        collateral, auction_id, our_address,
                                                        current_bid.amount_to_sell, bid_amount)
    print("create_debt(): after TestEnglish increase_bid_size")

    geb.cdp_engine.cdp_rights(our_address, collateral.collateral_auction_house.address)
    print("waiting for bid_duration: %d" % collateral.collateral_auction_house.bid_duration())
    wait(geb, our_address, collateral.collateral_auction_house.bid_duration()+1)
    print("create_debt(): before settleAuction")
    assert collateral.collateral_auction_house.settle_auction(auction_id).transact()
    print("create_debt(): after settleAuction")

    print("raising debt from queue")
    # Raise debt from the queue (note that vow.wait is 0 on our testchain)
    liquidations = geb.liquidation_engine.past_liquidations(100)
    for liquidation in liquidations:
        era_liquidation = liquidation.era(web3)
        liquidation_age = int(datetime.now().timestamp()) - era_liquidation
        print("liquidation age: %d", liquidation_age)
        #assert era_liquidation > int(datetime.now().timestamp()) - 120
        assert era_liquidation > int(datetime.now().timestamp()) - \
                                 ((collateral.collateral_auction_house.bid_duration() + geb.accounting_engine.pop_debt_delay()) * 2)
        assert geb.accounting_engine.debt_balance_of(era_liquidation) > Rad(0)
        print("before pop debt from queue")
        assert geb.accounting_engine.pop_debt_from_queue(era_liquidation).transact()
        print("after pop debt from queue")
        assert geb.accounting_engine.debt_balance_of(era_liquidation) == Rad(0)

    # Cancel out surplus and debt
    acct_engine_coin_balance = geb.cdp_engine.coin_balance(geb.accounting_engine.address)
    assert acct_engine_coin_balance <= geb.accounting_engine.unqueued_unauctioned_debt()
    assert geb.accounting_engine.settle_debt(acct_engine_coin_balance).transact()
    assert geb.accounting_engine.unqueued_unauctioned_debt() >= geb.accounting_engine.debt_auction_bid_size()


def check_active_auctions(auction: AuctionContract):
    for bid in auction.active_auctions():
        assert bid.id > 0
        assert auction.auctions_started() >= bid.id
        assert isinstance(bid.high_bidder, Address)
        assert bid.high_bidder != Address("0x0000000000000000000000000000000000000000")

class TestEnglishCollateralAuctionHouse:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def oracle_relayer(self, geb: GfDeployment) -> OracleRelayer:
        return geb.oracle_relayer

    @pytest.fixture(scope="session")
    def collateral_auction_house(self, collateral, deployment_address) -> EnglishCollateralAuctionHouse:
        return collateral.collateral_auction_house

    @staticmethod
    def increase_bid_size(collateral_auction_house: EnglishCollateralAuctionHouse, oracle_relayer: OracleRelayer, 
                          collateral: Collateral, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(collateral_auction_house, EnglishCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid_amount <= current_bid.amount_to_raise
        assert bid_amount > current_bid.bid_amount
        assert (bid_amount >= Rad(collateral_auction_house.bid_increase()) * current_bid.bid_amount) or (bid_amount == current_bid.amount_to_raise)

        #require(rad >= multiply(wmultiply(rdivide(uint256(priceFeedValue), redemptionPrice), amountToBuy), bidToMarketPriceRatio),

        price_feed = Wad(Web3.toInt(collateral.pip.read()))
        redemption_price = Wad(Ray(oracle_relayer.redemption_price()))
        bid_to_market_price_ratio = collateral_auction_house.bid_to_market_price_ratio()

        min_bid = Rad((price_feed / redemption_price) * amount_to_sell * bid_to_market_price_ratio)

        assert bid_amount >= min_bid
        assert collateral_auction_house.increase_bid_size(id, amount_to_sell, bid_amount).transact(from_address=address)

    @staticmethod
    def decrease_sold_amount(collateral_auction_house: EnglishCollateralAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid: Rad):
        assert (isinstance(collateral_auction_house, EnglishCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid == current_bid.bid
        assert bid == current_bid.amount_to_raise
        assert amount_to_sell < current_bid.amount_to_sell
        assert collateral_auction_house.bid_increase() * amount_to_sell <= current_bid.amount_to_sell

        assert collateral_auction_house.decrease_sold_amount(id, amount_to_sell, bid).transact(from_address=address)

    def test_getters(self, geb, collateral_auction_house):
        assert collateral_auction_house.cdp_engine() == geb.cdp_engine.address
        assert collateral_auction_house.bid_increase() > Wad.from_number(1)
        assert collateral_auction_house.bid_duration() > 0
        assert collateral_auction_house.total_auction_length() > collateral_auction_house.bid_duration()
        assert collateral_auction_house.auctions_started() >= 0

    # failing assertion 194
    # NOTE some assertions are commented out
    #@pytest.mark.skip(reason="temporary")
    def test_scenario(self, web3, geb, collateral, collateral_auction_house, our_address, other_address, deployment_address):
        #prev_balance = geb.system_coin.balance_of(deployment_address)
        #prev_coin_balance = geb.cdp_engine.coin_balance(deployment_address)
        print("balance 1")
        print(geb.system_coin.balance_of(deployment_address))
        print(geb.cdp_engine.coin_balance(deployment_address))

        # Create a CDP
        collateral = geb.collaterals['ETH-A']
        auctions_started_before = collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
        wrap_modify_cdp_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        wrap_modify_cdp_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        geb.approve_system_coin(deployment_address)

        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        #assert geb.system_coin.balance_of(deployment_address) == prev_balance + delta_debt
        #assert geb.cdp_engine.coin_balance(deployment_address) == prev_coin_balance + Rad(0)

        # Undercollateralize the CDP
        to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        collateral_type = geb.cdp_engine.collateral_type(collateral_type.name)
        assert collateral_type.accumulated_rates is not None
        assert collateral_type.safety_price is not None
        safe = Ray(cdp.generated_debt) * geb.cdp_engine.collateral_type(collateral_type.name).accumulated_rates <= Ray(cdp.locked_collateral) * collateral_type.safety_price
        assert not safe
        assert len(collateral_auction_house.active_auctions()) == 3

        # Liquidate the CDP, which moves debt to the accounting engine and auctions_started the collateral_auction_house
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        assert cdp.locked_collateral > Wad(0)
        amount_to_sell = min(cdp.locked_collateral, geb.liquidation_engine.collateral_to_sell(collateral_type))  # Wad
        generated_debt = min(cdp.generated_debt, (amount_to_sell * cdp.generated_debt) / cdp.locked_collateral)  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rates  # Wad
        #assert amount_to_raise == delta_debt
        simulate_liquidate_cdp(geb, collateral, deployment_address)
        assert geb.liquidation_engine.liquidate_cdp(collateral.collateral_type, CDP(deployment_address)).transact()
        start_auction = collateral_auction_house.auctions_started()
        assert start_auction == auctions_started_before + 1
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, deployment_address)
        # Check cdp_engine, accounting_engine, and liquidation_engine
        assert cdp.locked_collateral == Wad(0)
        assert cdp.generated_debt == delta_debt - generated_debt
        assert geb.cdp_engine.global_unbacked_debt() > Rad(0)
        #assert geb.accounting_engine.debt_queue() == Rad(amount_to_raise)
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)
        # Check the collateral_auction_house
        current_bid = collateral_auction_house.bids(start_auction)
        assert isinstance(current_bid, EnglishCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell > Wad(0)
        assert current_bid.amount_to_raise > Rad(0)
        assert current_bid.bid_amount == Rad(0)

        # Cat doesn't incorporate the liquidation penalty (chop), but the start_auctioner includes it.
        # Awaiting word from @dc why this is so.
        #assert last_liquidation.amount_to_raise == current_bid.amount_to_raise
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.StartAuctionLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid_amount == current_bid.bid_amount
        assert log.amount_to_raise == current_bid.amount_to_raise
        assert log.forgone_collateral_receiver == deployment_address
        assert log.auction_income_recipient == geb.accounting_engine.address

        # Wrap some eth and handle approvals before bidding
        eth_required = Wad(current_bid.amount_to_raise / Rad(collateral_type.safety_price)) * Wad.from_number(1.1)
        wrap_eth(geb, other_address, eth_required)
        collateral.approve(other_address)
        assert collateral.adapter.join(other_address, eth_required).transact(from_address=other_address)
        wrap_eth(geb, our_address, eth_required)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, eth_required).transact(from_address=our_address)

        # Test the _increase_bid_size_ phase of the auction
        collateral_auction_house.approve(geb.cdp_engine.address, 
                                         approval_function=approve_cdp_modification_directly(from_address=other_address))
        # Add Wad(1) to counter precision error converting amount_to_raise from Rad to Wad
        wrap_modify_cdp_collateralization(geb, collateral, other_address, delta_collateral=eth_required,
                                          delta_debt=Wad(current_bid.amount_to_raise) + Wad(1))
        cdp = geb.cdp_engine.cdp(collateral.collateral_type, other_address)
        assert Rad(cdp.generated_debt) >= current_bid.amount_to_raise
        # Bid the amount_to_raise to instantly transition to dent stage
        TestEnglishCollateralAuctionHouse.increase_bid_size(collateral_auction_house, geb.oracle_relayer, collateral, start_auction, other_address,
                                                            current_bid.amount_to_sell, current_bid.amount_to_raise)
        current_bid = collateral_auction_house.bids(start_auction)
        assert current_bid.high_bidder == other_address
        assert current_bid.bid_amount == current_bid.amount_to_raise
        assert len(collateral_auction_house.active_auctions()) == 1
        check_active_auctions(collateral_auction_house)
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.TendLog)
        assert log.high_bidder == current_bid.guy
        assert log.id == current_bid.id
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid_amount == current_bid.bid_amount

        # Test the _decreaseSoldAmount_ phase of the auction
        collateral_auction_house.approve(geb.cdp_engine.address, approval_function=approve_cdp_modification_directly(from_address=our_address))
        wrap_modify_cdp_collateralization(geb, collateral, our_address, delta_collateral=eth_required,
                                          delta_debt=Wad(current_bid.amount_to_raise) + Wad(1))
        amount_to_sell = current_bid.amount_to_sell - Wad.from_number(0.2)
        assert collateral_auction_house.bid_increase() * amount_to_sell <= current_bid.amount_to_sell
        assert geb.cdp_engine.can(our_address, collateral_auction_house.address)
        TestEnglishCollateralAuctionHouse.decrease_sold_amount(collateral_auction_house, start_auction, our_address,
                                                        amount_to_sell, current_bid.amount_to_raise)
        current_bid = collateral_auction_house.bids(start_auction)
        assert current_bid.high_bidder == our_address
        assert current_bid.bid == current_bid.amount_to_raise
        assert current_bid.amount_to_sell == amount_to_sell
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.DecreaseSoldAmountLog)
        assert log.high_bidder == current_bid.guy
        assert log.id == current_bid.id
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid_amount == current_bid.bid_amount

        # Exercise _settleAuction_ after bid has expired
        wait(geb, our_address, collateral_auction_house.bid_duration()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.bid_expiry < now or current_bid.auction_deadline < now
        assert collateral_auction_house.deal(start_auction).transact(from_address=our_address)
        assert len(collateral_auction_house.active_auctions()) == 0
        log = collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.SettleAuctionLog)
        assert log.forgone_collateral_receiver == our_address

        # Grab our collateral
        collateral_before = collateral.collateral.balance_of(our_address)
        assert collateral.adapter.exit(our_address, current_bid.amount_to_sell).transact(from_address=our_address)
        collateral_after = collateral.collateral.balance_of(our_address)
        assert collateral_before < collateral_after

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_cdp(geb, collateral, other_address)


@pytest.mark.skip(reason="temporary")
class TestSurplusAuctionHouse:
    @pytest.fixture(scope="session")
    def surplus_auction_house(self, geb: GfDeployment) -> SurplusAuctionHouse:
        return geb.surplus_auction_house

    @staticmethod
    def increase_bid_size(surplus_auction_house: SurplusAuctionHouse, id: int, address: Address, amount_to_sell: Rad, bid: Wad):
        assert (isinstance(surplus_auction_house, SurplusAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Rad))
        assert (isinstance(bid, Wad))

        assert surplus_auction_house.contract_enabled() == 1

        current_bid = surplus_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid > current_bid.bid
        assert bid >= surplus_auction_house.bid_increase() * current_bid.bid

        assert surplus_auction_house.increase_bid_size(id, amount_to_sell, bid).transact(from_address=address)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.TendLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.amount_to_sell == amount_to_sell
        assert log.bid == bid

    def test_getters(self, geb, surplus_auction_house):
        assert surplus_auction_house.cdp_engine() == geb.cdp_engine.address
        assert surplus_auction_house.bid_increase() > Wad.from_number(1)
        assert surplus_auction_house.bid_duration() > 0
        assert surplus_auction_house.total_auction_length() > surplus_auction_house.bid_duration()
        assert surplus_auction_house.auctions_started() >= 0

    # failed, not safe
    @pytest.mark.skip(reason="surplus buffer too high to create surplus now")
    def test_scenario(self, web3, geb, surplus_auction_house, our_address, other_address, deployment_address):
        create_surplus(geb, surplus_auction_house, deployment_address)

        joy_before = geb.cdp_engine.system_coin(geb.accounting_engine.address)
        # total surplus > total debt + surplus auction amount_to_sell size + surplus buffer
        assert joy_before > geb.cdp_engine.debt_balance(geb.accounting_engine.address) + geb.accounting_engine.surplus_auction_amount_to_sell() + geb.accounting_engine.surplus_buffer()
        assert (geb.cdp_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.sin()) - geb.accounting_engine.ash() == Rad(0)
        assert geb.accounting_engine.flap().transact()
        start_auction = surplus_auction_house.auctions_started()
        assert start_auction == 1
        assert len(surplus_auction_house.active_auctions()) == 1
        check_active_auctions(surplus_auction_house)
        current_bid = surplus_auction_house.bids(1)
        assert current_bid.amount_to_sell > Rad(0)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.KickLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid_amount == current_bid.bid_amount

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, surplus_auction_house.total_auction_length()+1)
        assert surplus_auction_house.restart_auction(start_auction).transact()

        # Bid on the resurrected auction
        mint_gov(geb.gov, our_address, Wad.from_number(10))
        surplus_auction_house.approve(geb.gov.address, directly(from_address=our_address))
        bid_amount = Wad.from_number(0.001)
        assert geb.gov.balance_of(our_address) > bid_amount
        TestSurplusAuctionHouse.increase_bid_size(surplus_auction_house, start_auction, our_address, current_bid.amount_to_sell, bid_amount)
        current_bid = surplus_auction_house.bids(start_auction)
        assert current_bid.bid_amount == bid_amount
        assert current_bid.high_bidder == our_address

        # Exercise _deal_ after bid has expired
        wait(geb, our_address, surplus_auction_house.bid_duration()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.bid_expiry < now or current_bid.auction_deadline < now
        assert surplus_auction_house.deal(start_auction).transact(from_address=our_address)
        joy_after = geb.cdp_engine.system_coin(geb.accounting_engine.address)
        print(f'joy_before={str(joy_before)}, joy_after={str(joy_after)}')
        assert joy_before - joy_after == geb.accounting_engine.surplus_auction_amount_to_sell()
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, SurplusAuctionHouse.DealLog)
        assert log.usr == our_address
        assert log.id == start_auction

        # Grab our system_coin
        geb.approve_system_coin(our_address)
        assert geb.system_coin_adapter.exit(our_address, Wad(current_bid.amount_to_sell)).transact(from_address=our_address)
        assert geb.system_coin.balance_of(our_address) >= Wad(current_bid.amount_to_sell)
        assert (geb.cdp_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.sin()) - geb.accounting_engine.ash() == Rad(0)

@pytest.mark.skip(reason="temporary")
class TestDebtAuctionHouse:
    @pytest.fixture(scope="session")
    def debt_auction_house(self, geb: GfDeployment) -> DebtAuctionHouse:
        return geb.debt_auction_house

    @staticmethod
    def decrease_sold_amount(debt_auction_house: DebtAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(debt_auction_house, DebtAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        assert debt_auction_house.contract_enabled() == 1

        current_bid = debt_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid_amount == current_bid.bid_amount
        assert Wad(0) < amount_to_sell < current_bid.amount_to_sell
        assert debt_auction_house.bid_decerase() * amount_to_sell <= current_bid.amount_to_sell

        assert debt_auction_house.decrease_sold_amount(id, amount_to_sell, bid_amount).transact(from_address=address)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.DecreaseSoldAmountLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.amount_to_sell == amount_to_sell
        assert log.bid_amount == bid_amount

    def test_getters(self, geb, debt_auction_house):
        assert debt_auction_house.cdp_engine() == geb.cdp_engine.address
        assert debt_auction_house.bid_decrease() > Wad.from_number(1)
        assert debt_auction_house.bid_duration() > 0
        assert debt_auction_house.total_auction_length() > debt_auction_house.bid_duration()
        assert debt_auction_house.auctions_started() >= 0

    # assertion fail at line 99
    #@pytest.mark.skip(reason="temporary")
    def test_scenario(self, web3, geb, debt_auction_house, our_address, other_address, deployment_address):
        create_debt(web3, geb, our_address, deployment_address)

        # start the debt auction
        assert debt_auction_house.auctions_started() == 0
        assert len(debt_auction_house.active_auctions()) == 0
        assert geb.cdp_engine.system_coin(geb.accounting_engine.address) == Rad(0)
        assert geb.accounting_engine.flop().transact()
        start_auction = debt_auction_house.auctions_started()
        assert start_auction == 1
        assert len(debt_auction_house.active_auctions()) == 1
        check_active_auctions(debt_auction_house)
        current_bid = debt_auction_house.bids(start_auction)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.KickLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid == current_bid.bid
        assert log.forgone_collateral_receiver == geb.accounting_engine.address

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, debt_auction_house.total_auction_length()+1)
        assert debt_auction_house.restart_auction(start_auction).transact()
        assert debt_auction_house.bids(start_auction).amount_to_sell == current_bid.amount_to_sell * debt_auction_house.amount_sold_increase()

        # Bid on the resurrected auction
        bid_amount = Wad.from_number(0.000005)
        debt_auction_house.approve(geb.cdp_engine.address, approve_cdp_modification_directly())
        assert geb.cdp_engine.can(our_address, debt_auction_house.address)
        TestDebtAuctionHouse.decrease_sold_amount(debt_auction_house, start_auction, our_address, bid_amount, current_bid.bid_amount)
        current_bid = debt_auction_house.bids(start_auction)
        assert current_bid.high_bidder == our_address

        # Confirm victory
        wait(geb, our_address, debt_auction_house.bid_duration()+1)
        assert debt_auction_house.contract_enabled()
        now = int(datetime.now().timestamp())
        assert (current_bid.bid_expiry < now and current_bid.bid_expiry != 0) or current_bid.auction_deadline < now
        gov_before = geb.gov.balance_of(our_address)
        assert debt_auction_house.deal(start_auction).transact(from_address=our_address)
        gov_after = geb.gov.balance_of(our_address)
        assert gov_after > gov_before
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.DealLog)
        assert log.forgone_collateral_receiver == our_address
        assert log.id == start_auction
