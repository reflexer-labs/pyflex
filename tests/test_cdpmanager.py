# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 EdNoepel
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

from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.cdpmanager import CDP


class TestCdpManager:

    def test_none(self, our_address: Address, geb: GfDeployment):
        assert geb.cdp_manager.first_cdp_id(our_address) == 0
        assert geb.cdp_manager.last_cdp_id(our_address) == 0
        assert geb.cdp_manager.cdp_count(our_address) == 0

    def test_open(self, our_address: Address, geb: GfDeployment):
        collateral_type = geb.collaterals['ETH-A'].collateral_type
        assert geb.cdp_manager.open_cdp(collateral_type, our_address).transact()
        assert geb.cdp_manager.last_cdp_id(our_address) == 1
        assert geb.cdp_manager.collateral_type(1).name == collateral_type.name
        assert geb.cdp_manager.owns_cdp(1) == our_address
        assert isinstance(geb.cdp_manager.cdp(1), CDP)

    def test_one(self, our_address: Address, geb: GfDeployment):
        assert geb.cdp_manager.first_cdp_id(our_address) == 1
        assert geb.cdp_manager.last_cdp_id(our_address) == 1
        assert geb.cdp_manager.cdp_count(our_address) == 1
