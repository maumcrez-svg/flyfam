// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import {ReentrancyGuard} from "./vendor/openzeppelin/ReentrancyGuard.sol";

struct PoolKey { address currency0; address currency1; uint24 fee; int24 tickSpacing; address hooks; }
struct SwapParams { bool zeroForOne; int256 amountSpecified; uint160 sqrtPriceLimitX96; }
interface IPoolManager {
    function unlock(bytes calldata data) external returns (bytes memory);
    function swap(PoolKey memory key, SwapParams memory params, bytes calldata hookData) external returns (int256);
    function sync(address currency) external;
    function settle() external payable returns (uint256);
    function take(address currency, address to, uint256 amount) external;
}
interface IPonsToken { function transferFrom(address from,address to,uint256 amount) external returns(bool); }

/// Exact inventory -> native ETH, only for the dedicated fly. No custody/admin sweep.
contract PonsV4Exit is ReentrancyGuard {
    address public immutable fly;
    address public immutable hook;
    IPoolManager public immutable manager;
    bytes32 private pending;
    error InvalidExit();
    event Sold(address indexed token, bytes32 indexed poolId, uint256 tokensIn, uint256 ethOut);
    constructor(address fly_,address manager_,address hook_) {
        if(fly_==address(0)||manager_==address(0)||hook_==address(0))revert InvalidExit();
        fly=fly_;manager=IPoolManager(manager_);hook=hook_;
    }
    function sell(PoolKey calldata key,uint128 amount,uint128 minimum,uint64 deadline)
        external nonReentrant returns(uint256 output)
    {
        if(msg.sender!=fly||key.currency0!=address(0)||key.currency1==address(0)||key.hooks!=hook
            ||amount==0||minimum==0||block.timestamp>deadline)revert InvalidExit();
        bytes memory data=abi.encode(key,amount,minimum);
        pending=keccak256(data);
        output=abi.decode(manager.unlock(data),(uint256));
        pending=bytes32(0);
        emit Sold(key.currency1,keccak256(abi.encode(key)),amount,output);
    }
    function unlockCallback(bytes calldata data) external returns(bytes memory) {
        if(msg.sender!=address(manager)||pending==bytes32(0)||keccak256(data)!=pending)revert InvalidExit();
        pending=bytes32(0); // Consume before any token interaction.
        (PoolKey memory key,uint128 amount,uint128 minimum)=abi.decode(data,(PoolKey,uint128,uint128));
        int256 delta=manager.swap(key,SwapParams(false,-int256(uint256(amount)),
            1461446703485210103287273052203988822378723970341),"");
        int128 output=int128(delta>>128);int128 input=int128(delta);
        if(input>=0||uint256(-int256(input))!=amount||output<=0||uint128(output)<minimum)revert InvalidExit();
        manager.sync(key.currency1);
        if(!IPonsToken(key.currency1).transferFrom(fly,address(manager),amount))revert InvalidExit();
        if(manager.settle()!=amount)revert InvalidExit();
        manager.take(address(0),fly,uint128(output));
        return abi.encode(uint256(uint128(output)));
    }
}
