"""The D11 tests, and where each of the owner's sixteen bullets is answered.

§7 of the D11 amendment lists sixteen things to test. Each is named here beside
the test that answers it, so a reader can check the list rather than trust it.

===================================== =========================================
owner bullet                          test
===================================== =========================================
recency and recent-count boundaries   ``test_admission_v2``:
                                      ``test_the_recent_count_boundary_is_exact``,
                                      ``test_the_recency_boundary_is_inclusive_at_exactly_sixty_seconds``,
                                      ``test_the_window_edge_is_half_open_at_the_start``
buys and sells counted symmetrically  ``test_admission_v2``:
                                      ``test_buys_and_sells_are_counted_symmetrically``,
                                      ``test_a_sell_alone_can_satisfy_the_recency_rule``
no future-event admission             ``test_admission_v2``:
                                      ``test_no_future_event_can_admit_a_candidate``,
                                      ``test_feeding_the_tape_more_history_than_the_cutoff_covers_changes_nothing``
duplicate / reverted events excluded  ``test_admission_v2``:
                                      ``test_a_duplicated_log_is_counted_once``,
                                      ``test_an_event_that_never_reached_the_tape_cannot_be_counted``,
                                      ``test_a_zero_amount_trade_is_not_a_valid_trade``
reversible readmission                ``test_admission_v2``:
                                      ``test_admission_is_reversible``,
                                      ``test_nothing_about_a_past_exclusion_is_remembered``
no stale-candidate fallback           ``test_admission_v2``:
                                      ``test_an_inactive_candidate_is_never_used_to_fill_a_slot``,
                                      ``test_fewer_than_six_qualifying_candidates_are_presented_as_they_are``,
                                      ``test_a_round_with_nothing_eligible_is_named_and_not_relaxed``
collector gaps ≠ genuine inactivity   ``test_admission_v2``:
                                      ``test_a_collector_gap_is_collector_lag_and_never_inactive``,
                                      ``test_a_whole_tracked_set_behind_the_collector_is_DATA_LAG_not_a_sea_of_inactive``;
                                      ``test_loop_v2``:
                                      ``test_a_collector_outage_names_the_round_DATA_LAG``
open positions preserved after        ``test_loop_v2``:
admission expiry                      ``test_a_held_position_is_observed_and_settled_after_its_token_goes_quiet``,
                                      ``test_admission_gates_entries_and_never_exits``
metadata and iteration-order          ``test_admission_v2``:
invariance                            ``test_the_verdict_does_not_depend_on_the_address``,
                                      ``test_the_verdict_does_not_depend_on_the_stable_id_or_the_iteration_order``
active-flat versus inactive inputs    ``test_context_v2``:
                                      ``test_a_busy_flat_market_and_a_dead_one_are_different_inputs``,
                                      ``test_quiet_for_ten_minutes_and_quiet_for_fifty_are_different_inputs``,
                                      ``test_the_four_owner_distinctions_are_measurable``
zero versus missing data              ``test_context_v2``:
                                      ``test_a_measured_zero_and_a_missing_measurement_are_not_the_same_object``,
                                      ``test_a_token_that_never_traded_reports_its_age_not_a_zero``,
                                      ``test_an_inconsistent_tape_is_never_priced_as_a_flat_market``
no manufactured sensory diversity     ``test_encoder_v2``:
                                      ``test_two_tokens_with_equal_raw_vectors_produce_equal_rate_vectors``,
                                      ``test_the_encoder_is_deterministic``
monotonic, sign-symmetric reward      ``test_reward_scale``:
magnitudes                            ``test_the_amount_is_monotonic_in_the_magnitude_of_the_outcome``,
                                      ``test_the_amount_is_sign_symmetric``,
                                      ``test_the_same_scale_serves_both_signs_and_nothing_is_subtracted``
neutral and extreme outcomes          ``test_reward_scale``:
                                      ``test_a_neutral_outcome_delivers_nothing``,
                                      ``test_an_extreme_outcome_is_capped_and_never_exceeds_the_cap``,
                                      ``test_a_vanishing_outcome_keeps_its_sign_and_a_tiny_amount``
one normalised learning event per     ``test_reward_scale``:
outcome                               ``test_one_settled_outcome_produces_exactly_one_learning_event``,
                                      ``test_a_mark_and_a_blocked_sell_teach_nothing``
incompatible encoder / checkpoint     ``test_encoder_v2``:
metadata rejected                     ``test_a_different_schema_hash_is_refused``,
                                      ``test_a_missing_schema_is_refused_unless_it_is_the_clean_reference``,
                                      ``test_the_journal_writes_the_schema_into_the_checkpoint_and_checks_it_back``
===================================== =========================================

Two more the wave owes, in ``test_hygiene``: the D11 scripts import nothing
from ``flytrade.pons.rpc``
(``test_the_d11_scripts_import_nothing_from_the_rpc_client``), and the IBM
reinforcement path is unchanged (``test_reward_scale``:
``test_the_ibm_reinforcement_path_is_byte_identical``).
"""
