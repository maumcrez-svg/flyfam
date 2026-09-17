"""The P1 tests, and where each paragraph of the addenda is answered.

The owner's P1 decision (``docs/SPEC.md``, 2026-09-13, Portuguese, verbatim)
and the nine Fable addenda beneath it are the list. Each claim is named here
beside the test that answers it, so a reader can check the list rather than
trust it. **Nothing in this wave is an experiment**: there is no hypothesis, no
registered threshold and no verdict, and no number any of these tests produces
is a measurement of Robinhood Chain, of PONS or of predictive skill.

===================================== =========================================
addendum / claim                      test
===================================== =========================================
2. the trader brain is the clean       ``test_trader_v1``:
reference, digest ba95b605…, stored    ``test_the_artifact_loads_to_the_registered_digest``,
under brains/trader-v1 with a          ``test_the_manifest_carries_every_field_addendum_2_names``,
manifest                               ``test_the_artifact_is_the_constructed_clean_reference``,
                                       ``test_the_manifest_records_the_two_checkpoints_it_was_verified_against``,
                                       ``test_the_committed_checkpoint_is_the_one_the_manifest_hashes``
2. the no-plasticity invariant: N      ``test_trader_v1``:
ticks, FROZEN, >= 1 settled episode    ``test_a_settled_episode_leaves_the_digest_exactly_where_it_was``,
-> the same digest                     ``test_the_loop_refuses_to_run_under_LEARN``
3(a). no wall-clock stop; the stop     ``test_loop_product``:
file, a signal, an invariant           ``test_no_wall_clock_stop_exists_in_the_product_driver``,
                                       ``test_the_stop_file_stops_it``,
                                       ``test_a_signal_stops_it``,
                                       ``test_a_brain_that_is_not_the_registered_one_refuses_the_start``,
                                       ``test_a_chain_that_is_not_4663_refuses_the_start``
3(b). the rolling hourly cap:          ``test_loop_product``:
THROTTLED and a wait, never an exit    ``test_the_window_counts_a_rolling_hour_off_the_ledger``,
                                       ``test_at_the_cap_the_loop_throttles_and_does_not_exit``,
                                       ``test_the_throttle_lifts_when_the_window_frees``,
                                       ``test_the_rolling_window_survives_a_restart``
3(c). resume from durable state; an    ``test_loop_product``:
open position survives a restart       ``test_a_restart_restores_the_account_the_cutoff_and_the_position``,
                                       ``test_the_open_position_is_not_closed_at_a_restart_mark``,
                                       ``test_a_pending_confirmation_is_restored_too``,
                                       ``test_episode_ids_stay_monotone_across_a_restart``,
                                       ``test_a_held_token_whose_tape_has_not_come_back_marks_nothing``
3(d). RPC errors retry with backoff    ``test_loop_product``:
and are counted                        ``test_a_transient_endpoint_error_is_retried_and_the_loop_survives``,
                                       ``test_the_backoff_doubles_and_is_capped``,
                                       ``test_a_range_refusal_is_not_retried_here``
3(e). HEARTBEAT every tick             ``test_feed``:
                                       ``test_every_tick_writes_exactly_one_heartbeat``
3(f). CREDIT computed by the           ``test_loop_product``:
existing absolute rule, recorded and   ``test_the_credit_is_the_absolute_rule_and_says_it_was_not_applied``,
never applied                          ``test_the_digest_is_unchanged_after_a_settled_episode``;
                                       ``test_config``:
                                       ``test_nothing_in_the_product_applies_a_weight_update``
4. the feed: one file per UTC day,     ``test_feed``:
state.json rewritten atomically,       ``test_one_sniff_per_tick_and_never_one_per_candidate``,
one SNIFF per tick                     ``test_the_day_file_is_named_for_the_utc_day``,
                                       ``test_state_json_is_rewritten_after_every_event``,
                                       ``test_state_json_carries_every_documented_key``,
                                       ``test_every_documented_key_exists_and_every_key_is_documented``,
                                       ``test_the_kinds_are_the_nine_and_they_are_canonical_event_types``,
                                       ``test_the_episode_history_carries_the_credit_label``,
                                       ``test_the_extremes_are_the_biggest_win_and_the_biggest_loss``
4. no endpoint, no key, no PII in      ``test_secrets``: every test in the module
either file
5. operation: the script and the       ``test_operation``:
user unit, no sudo, no linger          ``test_the_script_has_the_four_verbs``,
                                       ``test_the_script_and_the_unit_name_no_sudo_and_no_linger``,
                                       ``test_the_unit_is_a_user_unit_with_restart_and_an_environment_file``,
                                       ``test_the_installed_unit_is_the_committed_one``,
                                       ``test_status_opens_no_socket``
7. the observer vocabulary grows and   ``tests/d10/test_projection_fidelity.py`` (unchanged frames),
the committed projections do not move  ``tests/observer/test_isolation.py``;
                                       ``test_config``:
                                       ``test_the_nine_kinds_are_declared_in_the_projection``
7. no threshold, scale, admission      ``test_config``:
constant or reinforcement scale        ``test_every_restated_number_is_d11s_own``,
moved                                  ``test_the_d11_configuration_is_the_one_the_artifact_was_built_against``,
                                       ``test_the_product_names_no_method_outside_the_allowlist``,
                                       ``test_the_product_signs_nothing``
===================================== =========================================

``harness.py`` builds the whole worker over a **scripted endpoint** (see its
docstring, and ``tests/d10/scripted.py``'s): a chain of one block a second
whose logs are constructed so that a launch, an admission, an entry, a mark and
a settlement can happen inside forty ticks of a fake clock. The decoder is
scripted in the tests that need a position, and only its *action* is: every
number it reports is the real decoder's.
"""
