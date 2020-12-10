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

from pyflex import Address, Transact
from pyflex.approval import directly, approve_safe_modification_directly
from pyflex.auctions import FixedDiscountCollateralAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, SAFE, LiquidationEngine, GebETHKeeperFlashProxy, GebMCKeeperFlashProxy
from pyflex.numeric import Wad, Ray, Rad
from tests.test_gf import wrap_eth, set_collateral_price, wait, wrap_modify_safe_collateralization
from tests.test_gf import cleanup_safe, max_delta_debt

#Transact.gas_estimate_for_bad_txs = 800000
#@pytest.mark.skip("tmp")
class TestETHKeeperFlashProxy:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def keeper_flash_proxy(self, collateral) -> GebETHKeeperFlashProxy:
        return collateral.keeper_flash_proxy

    @pytest.fixture(scope="session")
    def fixed_collateral_auction_house(self, collateral) -> FixedDiscountCollateralAuctionHouse:
        return collateral.collateral_auction_house

    @pytest.fixture(scope="session")
    def liquidation_engine(self, geb: GfDeployment, collateral) -> LiquidationEngine:
        return geb.liquidation_engine

    def test_getters(self, geb, collateral, keeper_flash_proxy, fixed_collateral_auction_house, liquidation_engine):
        if not isinstance(keeper_flash_proxy, GebETHKeeperFlashProxy):
            return

        assert keeper_flash_proxy.collateral_type() == collateral.collateral_type
        assert keeper_flash_proxy.auction_house() == fixed_collateral_auction_house.address 
        assert keeper_flash_proxy.liquidation_engine() == liquidation_engine.address 

        #assert keeper_flash_proxy.safe_engine() == geb.safe_engine.address

    #@pytest.mark.skip("tmp")
    def test_flash_settle_auction(self, web3, geb, collateral, keeper_flash_proxy, fixed_collateral_auction_house, our_address, other_address, deployment_address):
        if not isinstance(keeper_flash_proxy, GebETHKeeperFlashProxy):
            return
        
        #collateral = geb.collaterals['ETH-A']
        auctions_started_before = fixed_collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        '''
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)
        '''

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral_type.name)

        # Make sure the SAFE is not safe
        assert collateral_type.accumulated_rate is not None
        assert collateral_type.safety_price is not None
        safe = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate <= \
               Ray(safe.locked_collateral) * collateral_type.safety_price

        assert not safe
        assert len(fixed_collateral_auction_house.active_auctions()) == 0
        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Ensure there is no saviour
        saviour = geb.liquidation_engine.safe_saviours(collateral.collateral_type, deployment_address)
        assert saviour == Address('0x0000000000000000000000000000000000000000')

        # Liquidate the SAFE
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        '''
        assert safe.locked_collateral > Wad(0)
        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt
        '''

        # Ensure safe can be liquidated
        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)

        assert geb.liquidation_engine.liquidate_safe(collateral_type, safe).transact()
        liquidated_id = collateral.collateral_auction_house.auctions_started()
        assert liquidated_id == auctions_started_before + 1

        eth_before = web3.eth.getBalance(our_address.address)
        # liquidate and settle
        #assert collateral.keeper_flash_proxy.liquidate_and_settle_safe(safe).transact(gas=800000, from_address=our_address)
        assert collateral.keeper_flash_proxy.settle_auction(liquidated_id).transact(from_address=our_address)

        eth_after = web3.eth.getBalance(our_address.address)
        print(f"Ether profit {(eth_after - eth_before)/1000000000000000000}")
        assert eth_after > eth_before

        # Ensure auction was started
        auction_id = fixed_collateral_auction_house.auctions_started()
        assert auction_id == auctions_started_before + 1

        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Check safe_engine, accounting_engine, and liquidation_engine
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)

        # Check the fixed_collateral_auction_house
        current_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(current_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell == Wad(0)
        assert current_bid.amount_to_raise == Rad(0)
        assert current_bid.raised_amount == Rad(0)
        assert current_bid.sold_amount == Wad(0)

        # Ensure auction has ended
        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)

    #@pytest.mark.skip("tmp")
    def test_flash_liquidate_and_settle_auction(self, web3, geb, collateral, keeper_flash_proxy, fixed_collateral_auction_house,
                                                our_address, other_address, deployment_address):
        if not isinstance(keeper_flash_proxy, GebETHKeeperFlashProxy):
            return

        #collateral = geb.collaterals['ETH-A']
        auctions_started_before = fixed_collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        '''
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)
        '''

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral_type.name)

        # Make sure the SAFE is not safe
        assert collateral_type.accumulated_rate is not None
        assert collateral_type.safety_price is not None
        safe = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate <= \
               Ray(safe.locked_collateral) * collateral_type.safety_price

        assert not safe
        assert len(fixed_collateral_auction_house.active_auctions()) == 0
        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Ensure there is no saviour
        saviour = geb.liquidation_engine.safe_saviours(collateral.collateral_type, deployment_address)
        assert saviour == Address('0x0000000000000000000000000000000000000000')

        # Liquidate the SAFE
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        '''
        assert safe.locked_collateral > Wad(0)
        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt
        '''

        # Ensure safe can be liquidated
        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)

        eth_before = web3.eth.getBalance(our_address.address)
        # liquidate and settle
        assert collateral.keeper_flash_proxy.liquidate_and_settle_safe(safe).transact(from_address=our_address)
        eth_after = web3.eth.getBalance(our_address.address)
        print(f"Ether profit {(eth_after - eth_before)/1000000000000000000}")
        assert eth_after > eth_before

        # Ensure auction was started
        auction_id = fixed_collateral_auction_house.auctions_started()
        assert auction_id == auctions_started_before + 1

        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Check safe_engine, accounting_engine, and liquidation_engine
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)

        # Check the fixed_collateral_auction_house
        current_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(current_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell == Wad(0)
        assert current_bid.amount_to_raise == Rad(0)
        assert current_bid.raised_amount == Rad(0)
        assert current_bid.sold_amount == Wad(0)

        # Ensure auction has ended
        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)

#@pytest.mark.skip("tmp")
class TestMCKeeperFlashProxy:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def mc_keeper_flash_proxy(self, geb) -> GebMCKeeperFlashProxy:
        return geb.mc_keeper_flash_proxy

    @pytest.fixture(scope="session")
    def fixed_collateral_auction_house(self, collateral) -> FixedDiscountCollateralAuctionHouse:
        return collateral.collateral_auction_house

    @pytest.fixture(scope="session")
    def liquidation_engine(self, geb: GfDeployment, collateral) -> LiquidationEngine:
        return geb.liquidation_engine

    def test_getters(self, geb, collateral, mc_keeper_flash_proxy, fixed_collateral_auction_house, liquidation_engine):
        if not isinstance(mc_keeper_flash_proxy, GebMCKeeperFlashProxy):
            return

        assert mc_keeper_flash_proxy.liquidation_engine() == liquidation_engine.address 

    #@pytest.mark.skip("tmp")
    def test_flash_settle_auction(self, web3, geb, collateral, mc_keeper_flash_proxy, fixed_collateral_auction_house,
                                  our_address, other_address, deployment_address):
        if not isinstance(mc_keeper_flash_proxy, GebMCKeeperFlashProxy):
            return
        
        auctions_started_before = fixed_collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        '''
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)
        '''

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral_type.name)

        # Make sure the SAFE is not safe
        assert collateral_type.accumulated_rate is not None
        assert collateral_type.safety_price is not None
        safe = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate <= \
               Ray(safe.locked_collateral) * collateral_type.safety_price

        assert not safe
        assert len(fixed_collateral_auction_house.active_auctions()) == 0
        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Ensure there is no saviour
        saviour = geb.liquidation_engine.safe_saviours(collateral.collateral_type, deployment_address)
        assert saviour == Address('0x0000000000000000000000000000000000000000')

        # Liquidate the SAFE
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        '''
        assert safe.locked_collateral > Wad(0)
        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt
        '''

        # Ensure safe can be liquidated
        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)

        assert geb.liquidation_engine.liquidate_safe(collateral_type, safe).transact()
        liquidated_id = collateral.collateral_auction_house.auctions_started()
        assert liquidated_id == auctions_started_before + 1

        eth_before = web3.eth.getBalance(our_address.address)
        # liquidate and settle
        #assert collateral.keeper_flash_proxy.liquidate_and_settle_safe(safe).transact(gas=800000, from_address=our_address)
        assert mc_keeper_flash_proxy.settle_auction(collateral.adapter.address, liquidated_id).transact(from_address=our_address)

        eth_after = web3.eth.getBalance(our_address.address)
        print(f"Ether profit {(eth_after - eth_before)/1000000000000000000}")
        assert eth_after > eth_before

        # Ensure auction was started
        auction_id = fixed_collateral_auction_house.auctions_started()
        assert auction_id == auctions_started_before + 1

        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Check safe_engine, accounting_engine, and liquidation_engine
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)

        # Check the fixed_collateral_auction_house
        current_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(current_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell == Wad(0)
        assert current_bid.amount_to_raise == Rad(0)
        assert current_bid.raised_amount == Rad(0)
        assert current_bid.sold_amount == Wad(0)

        # Ensure auction has ended
        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)

    #@pytest.mark.skip("tmp")
    def test_flash_liquidate_and_settle_auction(self, web3, geb, collateral, mc_keeper_flash_proxy, fixed_collateral_auction_house,
                                                our_address, other_address, deployment_address):
        if not isinstance(mc_keeper_flash_proxy, GebETHKeeperFlashProxy):
            return

        #collateral = geb.collaterals['ETH-A']
        auctions_started_before = fixed_collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        '''
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)
        '''

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral_type.name)

        # Make sure the SAFE is not safe
        assert collateral_type.accumulated_rate is not None
        assert collateral_type.safety_price is not None
        safe = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate <= \
               Ray(safe.locked_collateral) * collateral_type.safety_price

        assert not safe
        assert len(fixed_collateral_auction_house.active_auctions()) == 0
        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Ensure there is no saviour
        saviour = geb.liquidation_engine.safe_saviours(collateral.collateral_type, deployment_address)
        assert saviour == Address('0x0000000000000000000000000000000000000000')

        # Liquidate the SAFE
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        '''
        assert safe.locked_collateral > Wad(0)
        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt
        '''

        # Ensure safe can be liquidated
        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)

        eth_before = web3.eth.getBalance(our_address.address)
        # liquidate and settle
        assert collateral.keeper_flash_proxy.liquidate_and_settle_safe(safe).transact(from_address=our_address)
        eth_after = web3.eth.getBalance(our_address.address)
        print(f"Ether profit {(eth_after - eth_before)/1000000000000000000}")
        assert eth_after > eth_before

        # Ensure auction was started
        auction_id = fixed_collateral_auction_house.auctions_started()
        assert auction_id == auctions_started_before + 1

        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Check safe_engine, accounting_engine, and liquidation_engine
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)

        # Check the fixed_collateral_auction_house
        current_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(current_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell == Wad(0)
        assert current_bid.amount_to_raise == Rad(0)
        assert current_bid.raised_amount == Rad(0)
        assert current_bid.sold_amount == Wad(0)

        # Ensure auction has ended
        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)
