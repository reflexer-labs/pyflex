# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 grandizzy
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

from web3 import Web3

from pyflex import Contract, Address, Transact
from pyflex.numeric import Wad


# TODO: Complete implementation and unit test
class OSM(Contract):
    """A client for the `OSM` contract.

    You can find the source code of the `OSM` contract here:
    <https://github.com/reflexer-labs/geb-fsm/blob/master/src/OSM.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `OSM` contract.
    """

    abi = Contract._load_abi(__name__, 'abi/OSM.abi')
    bin = Contract._load_bin(__name__, 'abi/OSM.bin')

    def __init__(self, web3: Web3, address: Address):
        assert (isinstance(web3, Web3))
        assert (isinstance(address, Address))

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def has_value(self) -> bool:
        """Checks whether this instance contains a value.

        Returns:
            `True` if this instance contains a value, which can be read. `False` otherwise.
        """
        return self._contract.functions.getResultWithValidity().call()[1]

    def last_update_time(self) -> int:
        """ Returns last update time in secs

        Returns:
            Epoch time in seconds
        """
        return self._contract.functions.lastUpdateTime().call()

    def update_delay(self) -> int:
        """ Returns number of seconds that must pass between updates

        Returns:
            Number of seconds
        """
        return self._contract.functions.updateDelay().call()

    def passed_delay(self) -> bool:
        """ Check if update delay has passed

        Returns:
            `True` if time since last update is greater than required delay. `False` otherwise.
        """
        return self._contract.functions.lastUpdateTime().call()

    def read(self) -> int:
        """Reads the current value from this instance

        If this instance does not contain a value, throws an exception.

        Returns:
            An integer with the current value of this instance.
        """
        return self._contract.functions.read().call()

    def update_result(self) -> Transact:
        """Populates this instance with a new value.

            A :py:class:`pyflex.Transact` instance, which can be used to trigger the transaction.
        """

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'updateResult', [])

    def __repr__(self):
        return f"OSM('{self.address}')"
