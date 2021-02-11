""" Print out stats about the current system """
import os
import time
from web3 import Web3, HTTPProvider
from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad
from pyflex.model import Token
#from pyexchange.uniswapv2 import UniswapV2

ETH_RPC_URL = os.environ['ETH_RPC_URL']

web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL, request_kwargs={"timeout": 60}))
while web3.eth.syncing:
    print("Node is syncing")
    time.sleep(5)

print(f"Current block number: {web3.eth.blockNumber}")
web3.eth.defaultAccount = os.environ['ETH_ACCOUNT']
register_keys(web3, [os.environ['ETH_KEYPASS']])

geb = GfDeployment.from_node(web3, 'rai')
our_address = Address(web3.eth.defaultAccount)
collateral = geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)

collateral = geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)


#Uniswap
'''
token_syscoin = Token("Syscoin", Address(geb.system_coin.address), 18)
token_weth = Token("WETH", collateral.collateral.address, 18)
weth_syscoin_path = [token_weth.address.address, geb.system_coin.address.address]

syscoin_eth_uniswap = UniswapV2(web3, token_syscoin, token_weth, our_address,
                                geb.uniswap_router, geb.uniswap_factory)

pair_address = syscoin_eth_uniswap.pair_address
'''

print("SAFE Engine")
print("-------------------------------")
print(f"address                            {str(geb.safe_engine.address.address)}")
print(f"global debt                        {float(str(geb.safe_engine.global_debt())):.2f}")
print(f"global debt ceiling                {float(str(geb.safe_engine.global_debt_ceiling())):.2f}")
print(f"global unbacked debt               {float(str(geb.safe_engine.global_unbacked_debt())):.2f}")
print(f"collateral_type.safety_price       {float(str(collateral_type.safety_price)):.2f}")
print(f"collateral_type.liquidation_price  {float(str(collateral_type.liquidation_price)):.2f}")
print(f"collateral_type.debt_ceiling       {float(str(collateral_type.debt_ceiling)):.2f}")
print(f"collateral_type.debt_floor         {float(str(collateral_type.debt_floor)):.2f}")
print("")
print("Accounting Engine")
print("-------------------------------")
print(f"address                            {str(geb.accounting_engine.address.address)}")
print(f"total queued debt                  {float(str(geb.accounting_engine.total_queued_debt())):.2f}")
print(f"total on auction debt              {float(str(geb.accounting_engine.total_on_auction_debt())):.2f}")
print(f"unqueued_unauctioned_debt          {float(str(geb.accounting_engine.unqueued_unauctioned_debt())):.2f}")
print(f"pop debt delay                     {geb.accounting_engine.pop_debt_delay()}")
print(f"surplus auction delay              {geb.accounting_engine.surplus_auction_delay()}")
print(f"surplus buffer                     {float(str(geb.accounting_engine.surplus_buffer())):.2f}")
print(f"surplus auction amount to sell     {float(str(geb.accounting_engine.surplus_auction_amount_to_sell())):.2f}")
print(f"debt auction bid size              {float(str(geb.accounting_engine.debt_auction_bid_size())):.2f}")
print(f"accounting engine coin balance     {float(str(geb.safe_engine.coin_balance(geb.accounting_engine.address))):.2f}")
print(f"accounting engine debt balance     {float(str(geb.safe_engine.debt_balance(geb.accounting_engine.address))):.2f}")
print("")
print("Liquidation Engine")
print("-------------------------------")
print(f"address                            {str(geb.liquidation_engine.address.address)}")
print(f"liquidation penalty                {float(str(geb.liquidation_engine.liquidation_penalty(collateral_type))):.2f}")
print(f"liquidation quantity               {float(str(geb.liquidation_engine.liquidation_quantity(collateral_type))):.2f}")
print(f"on_auction_system_coin_limit       {float(str(geb.liquidation_engine.on_auction_system_coin_limit())):.2f}")
print(f"current_on_auction_system_coins    {float(str(geb.liquidation_engine.current_on_auction_system_coins())):.2f}")
print("")
print("Oracle Relayer")
print("-------------------------------")
print(f"address                            {str(geb.oracle_relayer.address.address)}")
print(f"redemption price                   {float(str(geb.oracle_relayer.redemption_price())):.2f}")
print(f"redemption rate                    {float(str(geb.oracle_relayer.redemption_rate())):.8f}")
print("")
print("Collateral")
print("-------------------------------")
print(f"osm collateral price               {Wad(geb.collaterals['ETH-A'].osm.read())}")
print(f"last update time                   {geb.collaterals['ETH-A'].osm.last_update_time()}")
print(f"update delay                       {geb.collaterals['ETH-A'].osm.update_delay()}")
print(f"time till can update               {(geb.collaterals['ETH-A'].osm.last_update_time() + geb.collaterals['ETH-A'].osm.update_delay()) - int(time.time())}")
print("Tax Collector")
print("-------------------------------")
print(f"address                            {str(geb.safe_engine.address.address)}")
print(f"global stability fee               {float(str(geb.tax_collector.global_stability_fee())):.2f}")
print(f"collateral stability fee           {float(str(geb.tax_collector.stability_fee(collateral_type))):.2f}")
print("")

'''
print("Uniswap")
print("-------------------------------")
print(f"RAI/ETH price                      {syscoin_eth_uniswap.get_exchange_rate()}")
print(f"RAI/USD price                      {syscoin_eth_uniswap.get_exchange_rate() * Wad(geb.collaterals['ETH-A'].osm.read())}")
print(f"RAI/ETH pair WETH balance          {syscoin_eth_uniswap.get_exchange_balance(token_weth, pair_address)}")
print(f"RAI/ETH pair RAI balance           {syscoin_eth_uniswap.get_exchange_balance(token_syscoin, pair_address)}")
print("")
'''

print("Active Collateral Auctions")
print("-------------------------------")
print(geb.collaterals['ETH-A'].collateral_auction_house.active_auctions())
print("Active Debt Auctions")
print("-------------------------------")
print(geb.debt_auction_house.active_auctions())
print("Active Surplus Auctions")
print("-------------------------------")
print(geb.surplus_auction_house.active_auctions())
