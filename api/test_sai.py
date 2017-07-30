# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2017 reverendus
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

from api import Address
from api.conftest import SaiDeployment
from api.feed import DSValue
from api.numeric import Wad, Ray


class TestSai:
    def test_join_and_exit(self, sai: SaiDeployment):
        # given
        assert sai.skr.balance_of(sai.our_address) == Wad(0)
        assert sai.skr.total_supply() == Wad(0)

        # when
        sai.tub.join(Wad.from_number(5))

        # then
        assert sai.skr.balance_of(sai.our_address) == Wad.from_number(5)
        assert sai.skr.total_supply() == Wad.from_number(5)

        # when
        sai.tub.exit(Wad.from_number(4))

        # then
        assert sai.skr.balance_of(sai.our_address) == Wad.from_number(1)
        assert sai.skr.total_supply() == Wad.from_number(1)

    def test_cork_and_hat(self, sai: SaiDeployment):
        # given
        assert sai.tub.hat() == Wad(0)

        # when
        sai.tub.cork(Wad.from_number(150000))

        # then
        assert sai.tub.hat() == Wad.from_number(150000)

    def test_crop_and_tax(self, sai: SaiDeployment):
        # given
        assert sai.tub.tax() == Ray.from_number(1)

        # when
        sai.tub.crop(Ray.from_number(1.00000000000000002))

        # then
        assert sai.tub.tax() == Ray.from_number(1.00000000000000002)

    def test_cuff_and_mat(self, sai: SaiDeployment):
        # given
        assert sai.tub.mat() == Ray.from_number(1)

        # when
        sai.tub.cuff(Ray.from_number(1.5))

        # then
        assert sai.tub.mat() == Ray.from_number(1.5)

    def test_chop_and_axe(self, sai: SaiDeployment):
        # given
        assert sai.tub.axe() == Ray.from_number(1)
        sai.tub.cuff(Ray.from_number(1.5))

        # when
        sai.tub.chop(Ray.from_number(1.2))

        # then
        assert sai.tub.axe() == Ray.from_number(1.2)

    def test_coax_and_way(self, sai: SaiDeployment):
        # given
        assert sai.tub.way() == Ray.from_number(1)

        # when
        sai.tub.coax(Ray.from_number(1.00000000000000007))

        # then
        assert sai.tub.way() == Ray.from_number(1.00000000000000007)

    def test_sai(self, sai: SaiDeployment):
        assert sai.tub.sai() == sai.sai.address

    def test_gem(self, sai: SaiDeployment):
        assert sai.tub.gem() == sai.gem.address

    def test_skr(self, sai: SaiDeployment):
        assert sai.tub.skr() == sai.skr.address

    def test_jug_pip(self, sai: SaiDeployment):
        assert isinstance(sai.tub.jug(), Address)
        assert isinstance(sai.tub.pip(), Address)

    def test_tip(self, sai: SaiDeployment):
        assert isinstance(sai.tub.tip(), Address)

    def test_reg(self, sai: SaiDeployment):
        assert sai.tub.reg() == 0

    def test_per(self, sai: SaiDeployment):
        assert sai.tub.per() == Ray.from_number(1.0)

    def test_tag(self, sai: SaiDeployment):
        # when
        DSValue(web3=sai.web3, address=sai.tub.pip()).poke_with_int(Wad.from_number(250.45).value)

        # then
        assert sai.tub.tag() == Wad.from_number(250.45)