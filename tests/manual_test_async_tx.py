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

import asyncio
import logging
import os
import sys
import threading
import time

from pyflex import Address, web3_via_http
from pyflex.deployment import GfDeployment
from pyflex.gas import FixedGasPrice, GeometricGasPrice
from pyflex.keys import register_keys
from pyflex.numeric import Wad

logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
# reduce logspew
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)

pool_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10

#web3 = Web3(HTTPProvider(endpoint_uri=os.environ['ETH_RPC_URL'], request_kwargs={"timeout": 60}))
web3 = web3_via_http(endpoint_uri=os.environ['ETH_RPC_URL'], http_pool_size=pool_size)
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass

geb = GfDeployment.from_node(web3, 'rai')
our_address = Address(web3.eth.defaultAccount)

weth = geb.collaterals['ETH-A'].collateral

GWEI = 1000000000
slow_gas = GeometricGasPrice(initial_price=int(15 * GWEI), every_secs=42, max_price=200 * GWEI)
fast_gas = GeometricGasPrice(initial_price=int(30 * GWEI), every_secs=42, max_price=200 * GWEI)

from mock import MagicMock

class TestApp:

    def main(self):
        self.test_replacement()
        self.test_simultaneous()
        self.shutdown()

    def start_ignoring_transactions(self):
        """ Allows an async tx to be created and leaves it trapped in Transact's event loop """
        self.original_send_transaction = web3.eth.sendTransaction
        self.original_get_transaction = web3.eth.getTransaction
        self.original_tx_count = web3.eth.getTransactionCount
        self.original_nonce = web3.eth.getTransactionCount(our_address.address)

        web3.eth.sendTransaction = MagicMock(return_value='0xaaaaaaaaaabbbbbbbbbbccccccccccdddddddddd')
        web3.eth.getTransaction = MagicMock(return_value={'nonce': self.original_nonce})
        web3.eth.getTransactionCount = MagicMock(return_value=0)

        logging.debug(f"Started ignoring async transactions at nonce {self.original_nonce}")

    def end_ignoring_transactions(self, ensure_next_tx_is_replacement=True):
        """ Stops trapping an async tx, with a facility to ensure the next tx is a replacement (where desired) """
        def second_send_transaction(transaction):
            # Ensure the second transaction gets sent with the same nonce, replacing the first transaction.
            assert transaction['nonce'] == self.original_nonce
            # Restore original behavior for the third transaction.
            web3.eth.sendTransaction = self.original_send_transaction

            # TestRPC doesn't support `sendTransaction` calls with the `nonce` parameter
            # (unlike proper Ethereum nodes which handle it very well)
            transaction_without_nonce = {key: transaction[key] for key in transaction if key != 'nonce'}
            return self.original_send_transaction(transaction_without_nonce)

        # Give the previous Transact a chance to enter its event loop
        time.sleep(0.05)

        if ensure_next_tx_is_replacement:
            web3.eth.sendTransaction = MagicMock(side_effect=second_send_transaction)
        else:
            web3.eth.sendTransaction = self.original_send_transaction
        web3.eth.getTransaction = self.original_get_transaction
        web3.eth.getTransactionCount = self.original_tx_count

        logging.debug("Finished ignoring async transactions")

    def _test_replacement(self):
        first_tx = weth.deposit(Wad(4))
        logging.info(f"Submitting first TX with gas price deliberately too low")
        self.start_ignoring_transactions()
        self._run_future(first_tx.transact_async(gas_price=slow_gas))
        time.sleep(0.1)
        self.end_ignoring_transactions()

        second_tx = weth.deposit(Wad(6))
        logging.info(f"Replacing first TX with legitimate gas price")
        second_tx.transact(replace=first_tx, gas_price=fast_gas)

        assert first_tx.replaced

    def test_replacement(self):
        first_tx = weth.deposit(Wad(4))
        logging.info(f"Submitting first TX with gas price deliberately too low")
        self.start_ignoring_transactions()
        self._run_future(first_tx.transact_async(gas_price=slow_gas))
        time.sleep(0.1)
        self.end_ignoring_transactions()
        while threading.active_count() > 1:
            print("> 1 thread")
            #asyncio.sleep(0.4)
            time.sleep(0.4)

        second_tx = weth.deposit(Wad(6))
        logging.info(f"Replacing first TX with legitimate gas price")
        self._run_future(second_tx.transact_async(gas_price=fast_gas))
        time.sleep(30)
        #second_tx.transact(replace=first_tx, gas_price=fast_gas)

        assert first_tx.replaced
    def _test_simultaneous(self):
        self._run_future(weth.deposit(Wad(1)).transact_async(gas_price=fast_gas))
        self._run_future(weth.deposit(Wad(3)).transact_async(gas_price=fast_gas))
        self._run_future(weth.deposit(Wad(5)).transact_async(gas_price=fast_gas))
        self._run_future(weth.deposit(Wad(7)).transact_async(gas_price=fast_gas))
        time.sleep(33)

    def _shutdown(self):
        balance = weth.balance_of(our_address)
        if Wad(0) < balance < Wad(100):  # this account's tiny WETH balance came from this test
            logging.info(f"Unwrapping {balance} WETH")
            assert weth.withdraw(balance).transact(gas_price=fast_gas)
        elif balance >= Wad(22):  # user already had a balance, so unwrap what a successful test would have consumed
            logging.info(f"Unwrapping 22 WETH")
            assert weth.withdraw(Wad(22)).transact(gas_price=fast_gas)

    @staticmethod
    def _run_future(future):
        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                asyncio.get_event_loop().run_until_complete(future)
            finally:
                loop.close()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()


if __name__ == '__main__':
    TestApp().main()
