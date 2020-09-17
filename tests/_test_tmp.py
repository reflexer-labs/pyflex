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
from pyflex.approval import approve_safe_modification_directly
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, CoinJoin, BasicCollateralJoin, CollateralType, SafeEngine, AccountingEngine
from pyflex.feed import DSValue
from pyflex.numeric import Wad, Ray, Rad
from pyflex.oracles import OSM
from pyflex.token import DSToken, DSEthToken, ERC20Token
from tests.conftest import validate_contracts_loaded


@pytest.fixture
def safe(our_address: Address, geb: GfDeployment):
    collateral = geb.collaterals['ETH-A']
    safe = geb.safe_engine.safe(collateral.collateral_type, our_address)
    assert safe.collateral_type is not None
    assert safe.collateral_type == collateral.collateral_type
    return safe


def wrap_eth(geb: GfDeployment, address: Address, amount: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    collateral = geb.collaterals['ETH-A']
    assert isinstance(collateral.collateral, DSEthToken)
    assert collateral.collateral.deposit(amount).transact(from_address=address)

def mint_prot(prot: DSToken, recipient_address: Address, amount: Wad):
    assert isinstance(prot, DSToken)
    assert isinstance(recipient_address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    deployment_address = Address("0x00a329c0648769A73afAc7F9381E08FB43dBEA72")
    assert prot.mint(amount).transact(from_address=deployment_address)
    assert prot.balance_of(deployment_address) > Wad(0)
    assert prot.approve(recipient_address).transact(from_address=deployment_address)
    assert prot.transfer(recipient_address, amount).transact(from_address=deployment_address)

def get_collateral_price(collateral: Collateral):
    assert isinstance(collateral, Collateral)
    return Wad(Web3.toInt(collateral.osm.read()))


def set_collateral_price(geb: GfDeployment, collateral: Collateral, price: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    osm = collateral.osm
    assert isinstance(osm, DSValue)

    print(f"Changing price of {collateral.collateral_type.name} to {price}")
    assert osm.update_result(price.value).transact(from_address=osm.get_owner())
    assert geb.oracle_relayer.update_collateral_price(collateral_type=collateral.collateral_type).transact(from_address=osm.get_owner())

    assert get_collateral_price(collateral) == price


def wait(geb: GfDeployment, address: Address, seconds: int):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert seconds > 0

    time.sleep(seconds)
    # Mine a block to increment block.timestamp
    wrap_eth(geb, address, Wad(1))


def wrap_modify_safe_collateralization(geb: GfDeployment, collateral: Collateral, address: Address, delta_collateral: Wad, delta_debt: Wad):
    """Wraps SafeEngine.modify_safe_collateralization for debugging purposes"""
    # given
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    assert isinstance(delta_collateral, Wad)
    assert isinstance(delta_debt, Wad)
    collateral_type = collateral.collateral_type

    # when
    collateral_before = geb.safe_engine.safe(collateral_type, address).locked_collateral
    debt_before = geb.safe_engine.safe(collateral_type, address).generated_debt

    # then
    assert geb.safe_engine.modify_safe_collateralization(collateral_type=collateral_type, safe_address=address,
                                                       delta_collateral=delta_collateral,
                                                       delta_debt=delta_debt).transact(from_address=address)

    assert geb.safe_engine.safe(collateral_type, address).locked_collateral == collateral_before + delta_collateral
    assert geb.safe_engine.safe(collateral_type, address).generated_debt == debt_before + delta_debt


def max_delta_debt(geb: GfDeployment, collateral: Collateral, our_address: Address) -> Wad:
    """Determines how much stablecoin should be reserved in an `safe` to make it as poorly collateralized as
    possible, such that a small change to the collateral price could trip the liquidation ratio."""
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    safe = geb.safe_engine.safe(collateral.collateral_type, our_address)
    collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)

    # change in generated debt = (collateral balance * collateral price with safety margin) - Safe's stablecoin debt
    delta_debt = safe.locked_collateral * collateral_type.safety_price - Wad(Ray(safe.generated_debt) * collateral_type.accumulated_rate)

    # change in debt must also take the rate into account
    delta_debt = delta_debt * Wad(Ray.from_number(1) / collateral_type.accumulated_rate)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(safe.generated_debt) + Rad(delta_debt)) >= collateral_type.debt_ceiling:
        print("max_delta_debt is avoiding collateral debt ceiling")
        delta_debt = Wad(collateral_type.debt_ceiling - Rad(safe.generated_debt))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = geb.safe_engine.global_debt() + Rad(collateral_type.accumulated_rate * delta_debt)
    debt_ceiling = Rad(collateral_type.debt_ceiling)
    if (debt + Rad(delta_debt)) >= debt_ceiling:
        print("max_delta_debt is avoiding total debt ceiling")
        delta_debt = Wad(debt - Rad(safe.generated_debt))

    assert delta_debt > Wad(0)
    return delta_debt


def cleanup_safe(geb: GfDeployment, collateral: Collateral, address: Address):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    safe = geb.safe_engine.safe(collateral.collateral_type, address)
    collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)

    # If tax_collector.tax_single has been called, we won't have sufficient system_coin to repay the Safe
    #if collateral_type.accumulated_rate > Ray.from_number(1):
    #    return

    # Return if this address doens't have enough system to coin to repay full debt
    amount_to_raise = Wad(Ray(safe.generated_debt) * collateral_type.accumulated_rate)
    if amount_to_raise > geb.system_coin.balance_of(address):
        return

    # Repay borrowed system coin
    geb.approve_system_coin(address)

    # Put all the user's system coin back into the safe engine
    if geb.system_coin.balance_of(address) >= Wad(0):
        assert geb.system_coin_adapter.join(address, geb.system_coin.balance_of(address)).transact(from_address=address)

    amount_to_raise = Wad(Ray(safe.generated_debt) * collateral_type.accumulated_rate)

    print(f'amount_to_raise={str(amount_to_raise)}, rate={str(collateral_type.accumulated_rate)}, system_coin={str(geb.safe_engine.coin_balance(address))}')
    if safe.generated_debt > Wad(0):
        wrap_modify_safe_collateralization(geb, collateral, address, Wad(0), amount_to_raise * -1)

    # Withdraw collateral
    collateral.approve(address)
    safe = geb.safe_engine.safe(collateral.collateral_type, address)
    # delta_collateral = Wad((Ray(safe.generated_debt) * collateral_type.accumulated_rate) / collateral_type.safety_price)
    # print(f'delta_collateral={str(delta_collateral)}, locked_collateral={str(safe.locked_collateral)}')
    if safe.generated_debt == Wad(0) and safe.locked_collateral > Wad(0):
        wrap_modify_safe_collateralization(geb, collateral, address, safe.locked_collateral * -1, Wad(0))

    assert collateral.adapter.exit(address, geb.safe_engine.token_collateral(collateral.collateral_type, address)).transact(from_address=address)
    TestSafeEngine.ensure_clean_safe(geb, collateral, address)

@pytest.fixture(scope="session")
def liquidate(web3: Web3, geb: GfDeployment, our_address: Address):
    collateral = geb.collaterals['ETH-A']

    # Add collateral to our Safe
    delta_collateral = Wad.from_number(1)
    wrap_eth(geb, our_address, delta_collateral)
    assert collateral.collateral.balance_of(our_address) >= delta_collateral
    assert collateral.adapter.join(our_address, delta_collateral).transact()
    wrap_modify_safe_collateralization(geb, collateral, our_address, delta_collateral, Wad(0))

    # Define required liquidation parameters
    to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)

    # Manipulate price to make our Safe underwater
    # Note this will only work on a testchain deployed with fixed prices, where OSM is a DSValue
    wrap_modify_safe_collateralization(geb, collateral, our_address, Wad(0), max_delta_debt(geb, collateral, our_address))
    set_collateral_price(geb, collateral, to_price)

    # Liquidate the Safe
    assert geb.liquidation_engine.can_liquidate(collateral.collateral_type, Safe(our_address))

    assert geb.liquidation_engine.liquidate_safe(collateral.collateral_type, Urn(our_address)).transact()


@pytest.fixture(scope="session")
def liquidation_event(web3: Web3, geb: GfDeployment, our_address: Address):
    liquidate(web3, geb, our_address)
    # Return the corresponding event
    return geb.liquidation_engine.past_liquidationss(1)[0]


class TestConfig:
    def test(self, web3: Web3, geb: GfDeployment):
        c = geb.collaterals['ETH-A']
        c.collateral_auction_house.approve(c.collateral_auction_house.safe_engine(), approve_safe_modification_directly())
