// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import {MerkleProof} from "./vendor/openzeppelin/MerkleProof.sol";
import {ReentrancyGuard} from "./vendor/openzeppelin/ReentrancyGuard.sol";

/// Native ETH bag profit. No admin withdrawal or root replacement.
/// Funder attests the off-chain accounting; custody/proofs are enforced here.
contract HolderVault is ReentrancyGuard {
    struct Distribution { bytes32 root; uint256 funded; uint256 paid; uint64 deadline; bool swept; }
    address public immutable funder;
    address payable public immutable flyBankroll;
    uint64 public immutable claimWindow;
    mapping(bytes32 => Distribution) public distributions;
    mapping(bytes32 => mapping(address => bool)) public claimed;
    error Unauthorized();
    error InvalidDistribution();
    error Unavailable();
    error InvalidProof();
    error TransferFailed();
    event DistributionOpened(bytes32 indexed bagId, bytes32 root, uint256 amount, uint64 deadline);
    event Claimed(bytes32 indexed bagId, address indexed account, uint256 amount);
    event DistributionExpired(bytes32 indexed bagId, uint256 unclaimed);
    event UnclaimedSwept(bytes32 indexed bagId, address indexed bankroll, uint256 amount);
    constructor(address funder_, address payable bankroll_, uint64 window_) {
        if (funder_ == address(0) || bankroll_ == address(0) || window_ == 0 || window_ > 365 days)
            revert InvalidDistribution();
        funder = funder_; flyBankroll = bankroll_; claimWindow = window_;
    }
    function openDistribution(bytes32 bagId, bytes32 root) external payable nonReentrant {
        if (msg.sender != funder) revert Unauthorized();
        if (bagId == bytes32(0) || root == bytes32(0) || msg.value == 0 || distributions[bagId].deadline != 0)
            revert InvalidDistribution();
        uint64 deadline = uint64(block.timestamp + claimWindow);
        distributions[bagId] = Distribution(root, msg.value, 0, deadline, false);
        emit DistributionOpened(bagId, root, msg.value, deadline);
    }
    function leaf(bytes32 bagId, address account, uint256 amount) public view returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(block.chainid, address(this), bagId, account, amount))));
    }
    // Anyone may relay; funds go only to the account bound by the proof.
    function claim(bytes32 bagId, address payable account, uint256 amount, bytes32[] calldata proof) external nonReentrant {
        Distribution storage d = distributions[bagId];
        if (d.deadline == 0 || block.timestamp >= d.deadline || d.swept || claimed[bagId][account]) revert Unavailable();
        if (account == address(0) || amount == 0 || !MerkleProof.verifyCalldata(proof, d.root, leaf(bagId, account, amount)))
            revert InvalidProof();
        if (amount > d.funded - d.paid) revert InvalidDistribution();
        claimed[bagId][account] = true; d.paid += amount;
        (bool ok,) = account.call{value: amount}("");
        if (!ok) revert TransferFailed();
        emit Claimed(bagId, account, amount);
    }
    function sweepExpired(bytes32 bagId) external nonReentrant {
        Distribution storage d = distributions[bagId];
        if (d.deadline == 0 || block.timestamp < d.deadline || d.swept) revert Unavailable();
        uint256 remainder = d.funded - d.paid;
        d.swept = true;
        emit DistributionExpired(bagId, remainder);
        if (remainder != 0) {
            (bool ok,) = flyBankroll.call{value: remainder}("");
            if (!ok) revert TransferFailed();
        }
        emit UnclaimedSwept(bagId, flyBankroll, remainder);
    }
}
