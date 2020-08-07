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
from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.auth import DSAuth
from pyflex.governance import DSPause, DSChief
from pyflex.numeric import Wad
from pyflex.deployment import GfDeployment
from datetime import datetime, timedelta

from tests.test_gf import mint_gov


@pytest.mark.skip(reason="not fully implemented")
class TestDSPause:
    def setup_method(self):
        self.web3 = Web3(HTTPProvider("http://localhost:8555"))
        self.web3.eth.defaultAccount = self.web3.eth.accounts[0]
        self.our_address = Address(self.web3.eth.defaultAccount)

        ds_auth = DSAuth.deploy(self.web3)
        self.ds_pause = DSPause.deploy(self.web3, 5, self.our_address, ds_auth)

        self.plan = DSPause.Plan(usr=self.our_address,
                                 fax=self.web3.toBytes(text='abi.encodeWithSignature("sig()")'),
                                 eta=(datetime.utcnow() + timedelta(seconds=10)))

    def test_drop(self):
        # assert self.ds_pause.plot(self.plan).transact()
        assert self.ds_pause.drop(self.plan).transact()

    def test_exec(self):
        # assert self.ds_pause.plot(self.plan).transact()
        assert self.ds_pause.exec(self.plan).transact()

class TestDSChief:
    def test_scenario(self, geb: GfDeployment, our_address: Address, other_address: Address):
        isinstance(geb, GfDeployment)
        isinstance(our_address, Address)

        prevBalance = geb.gov.balance_of(our_address)
        #amount = Wad.from_number(1000)
        amount = Wad.from_number(1)
        mint_gov(geb.gov, our_address, amount)
        assert geb.gov.balance_of(our_address) == amount + prevBalance

        # Lock gov in DS-Chief
        assert geb.gov.approve(geb.ds_chief.address).transact(from_address=our_address)
        assert geb.ds_chief.lock(amount).transact(from_address=our_address)
        assert geb.gov.balance_of(our_address) == prevBalance

        # Vote for our address
        assert geb.ds_chief.vote_yays([our_address.address]).transact(from_address=our_address)
        assert geb.ds_chief.etch([other_address.address]).transact(from_address=our_address)

        # Confirm that etch(our address) != etch(other address)
        etches = geb.ds_chief.past_etch(3)
        assert etches[0].slate !=  etches[-1].slate

        assert geb.ds_chief.get_approvals(our_address.address) == amount

        # Lift hat for our address
        assert geb.ds_chief.get_hat() != our_address
        assert geb.ds_chief.lift(our_address).transact(from_address=our_address)
        assert geb.ds_chief.get_hat() == our_address

        # Now vote for other address
        assert geb.ds_chief.vote_etch(etches[-1]).transact(from_address=our_address)
        assert geb.ds_chief.lift(other_address).transact(from_address=our_address)
        assert geb.ds_chief.get_hat() == other_address

        # TODO. Need to give DS-Chief approval to move/burn IOU tokens before
        # calling geb.ds_chief.free(amount)
        # Can fix in one of two ways:
        # 1.) Need to add IOU DStoken to GfDeployment
        # https://github.com/dapphub/ds-chief/blob/master/src/chief.sol#L65
        # 2.) Look for the "mint" event to determine the address of the IOU token
        # _past_events(self, contract, event, cls, number_of_past_blocks, event_filter)

        # assert geb.ds_chief.free(amount).transact(from_address=our_address)
        # assert geb.gov.balance_of(our_address) == amount
