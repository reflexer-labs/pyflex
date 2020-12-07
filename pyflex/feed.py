# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2017-2018 reverendus
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
from pyflex.auth import DSAuth


class DSValue(DSAuth):
    """A client for the `DSValue` contract, a single-value data feed.

    `DSValue` is a single-value data feed, which means it can be in one of two states.
    It can either contain a value (in which case `has_value()` returns `True` and the read methods
    return that value) or be empty (in which case `has_value()` returns `False` and the read
    methods throw exceptions).

    `DSValue` can be populated with a new value using `updateResult()` and cleared using `void()`.

    Everybody can read from a `DSValue`.
    Calling `updateResult()` and `void()` is usually whitelisted to some addresses only.
    upda

    The `DSValue` contract keeps the value as a 32-byte array (Ethereum `bytes32` type).
    Methods have been provided to cast it into `int`, read as hex etc.

    You can find the source code of the `DSValue` contract here:
    <https://github.com/dapphub/ds-value>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `DSValue` contract.
    """

    abi = Contract._load_abi(__name__, 'abi/DSValue.abi')
    bin = Contract._load_bin(__name__, 'abi/DSValue.bin')

    @staticmethod
    def deploy(web3: Web3):
        return DSValue(web3=web3, address=Contract._deploy(web3, DSValue.abi, DSValue.bin, []))

    def __init__(self, web3: Web3, address: Address):
        assert(isinstance(web3, Web3))
        assert(isinstance(address, Address))

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def has_value(self) -> bool:
        """Checks whether this instance contains a value.

        Returns:
            `True` if this instance contains a value, which can be read. `False` otherwise.
        """
        return self._contract.functions.getResultWithValidity().call()[1]

    def read(self) -> int:
        """Reads the current value from this instance

        If this instance does not contain a value, throws an exception.

        Returns:
            An integer with the current value of this instance.
        """
        return self._contract.functions.read().call()

    def update_result(self, new_value: int) -> Transact:
        """Populates this instance with a new value.

        Args:
            new_value: An integer of the new value to be set.

        Returns:
            A :py:class:`pyflex.Transact` instance, which can be used to trigger the transaction.
        """
        assert(isinstance(new_value, int))
        #assert(len(new_value) == 32)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'updateResult', [new_value])

    def restart_value(self) -> Transact:
        """Removes the current value from this instance.

        Returns:
            A :py:class:`pyflex.Transact` instance, which can be used to trigger the transaction.
        """
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartValue', [])

    def __repr__(self):
        return f"DSValue('{self.address}')"
