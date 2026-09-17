"""The D12 tests, and where each of the owner's paragraphs is answered.

The owner's D12 spec (``docs/SPEC.md``, 2026-09-13, Portuguese, verbatim) and
the fourteen Fable addenda beneath it are the list. Each claim is named here
beside the test that answers it, so a reader can check the list rather than
trust it.

===================================== =========================================
owner paragraph / addendum            test
===================================== =========================================
"o cérebro treinado virou              ``test_mirror``:
aproximadamente o negativo do          ``test_an_exact_negative_gives_tau_minus_one_and_slope_minus_one``,
cérebro virgem" — the mirror           ``test_an_exact_negative_with_an_offset_still_gives_tau_minus_one``,
diagnostic (addendum 5)                ``test_the_auc_of_the_negated_score_is_one_minus_the_auc``,
                                       ``test_kendall_tau_b_matches_a_brute_force_count_with_ties``;
                                       ``test_artifacts``:
                                       ``test_the_mirror_diagnostic_ran_on_the_existing_scores_with_no_brain``
"A recebe reward forte; ... F          ``test_rule``:
punishment forte" — the two owner      ``test_the_owners_two_examples_give_the_registered_signals``,
examples, both giving                  ``test_the_registered_file_carries_the_same_known_answer``
+1/+0.6/+0.2/-0.2/-0.6/-1
(addendum 3)
"Mesmo se os seis perderem             ``test_rule``:
dinheiro ... A foi a melhor escolha    ``test_a_cohort_that_all_lost_money_still_teaches_which_lost_least``;
relativa"                              ``test_school``:
                                       ``test_the_financial_net_and_the_signal_stay_two_columns``;
                                       ``test_artifacts``:
                                       ``test_every_cohort_is_zero_mean_and_bounded_and_reaches_the_extremes``
"Financeiramente continua              ``test_rule``:
aparecendo -3%. Não falsificamos       ``test_the_relative_rule_is_never_called_a_profit_reward``
lucro" — two columns, never merged     (``test_hygiene``)
"deve ser chamado explicitamente de    ``test_hygiene``:
relative/cohort reinforcement, não     ``test_the_relative_rule_is_never_called_a_profit_reward``,
de profit reward"                      ``test_the_registration_refuses_to_call_profit_learning``
ties, and a cohort too small to        ``test_rule``:
teach (addendum 3, n_min = 3)          ``test_ties_share_their_average_rank``,
                                       ``test_tied_nets_get_the_identical_signal``,
                                       ``test_a_wholly_tied_cohort_teaches_nothing_to_anyone``,
                                       ``test_ties_are_exact_on_integers_and_not_a_tolerance``,
                                       ``test_a_cohort_below_n_min_produces_no_lesson_at_all``,
                                       ``test_none_is_not_an_empty_list_and_not_a_list_of_zeros``;
                                       ``test_school``:
                                       ``test_a_cohort_below_n_min_teaches_nobody_and_is_counted``,
                                       ``test_a_cohort_that_drops_below_n_min_teaches_nobody``
"Não exigiria mais que ela compre      ``test_school``:
para poder aprender" — school mode     ``test_the_school_names_no_execution_verb_anywhere``,
opens no position (addendum 2)         ``test_the_registration_says_the_school_holds_no_position``;
                                       ``test_artifacts``:
                                       ``test_the_school_opened_no_position_and_took_no_trade``
"se num tick existem seis memecoins    ``test_artifacts``:
elegíveis, as seis podem virar         ``test_every_eligible_candidate_of_a_tick_became_a_lesson``,
experiências" — all eligible           ``test_the_school_presented_far_more_than_the_six_of_a_round``
presented, no cap, no rotation
"centenas ou milhares de lições,       ``test_artifacts``:
em vez de quinze"                      ``test_the_wave_applied_thousands_of_lessons_not_fifteen``
"e ainda tivemos 11/15 atualizações    ``test_rule``:
batendo no teto da escala 0,131" —     ``test_no_clipping_can_occur_and_no_cap_is_consulted``;
no clipping is possible                ``test_artifacts``:
                                       ``test_no_lesson_was_ever_clipped``
maturity: the lesson arrives 902 s     ``test_school``:
later and never earlier                ``test_a_lesson_can_never_mature_before_cutoff_plus_902``,
(addendum 2)                           ``test_the_maturity_tick_is_on_the_grid_and_is_the_first_one_that_qualifies``,
                                       ``test_on_this_grid_the_maturity_tick_is_always_cutoff_plus_930``;
                                       ``test_artifacts``:
                                       ``test_no_lesson_was_applied_before_its_outcome_existed``
no lesson is applied at a FROZEN       ``test_school``:
tick, and the boundary discards        ``test_a_lesson_inside_the_boundary_never_matures_at_a_frozen_tick``;
(addendum 2)                           ``test_artifacts``:
                                       ``test_no_lesson_was_applied_at_or_after_the_cutoff_T``
the pending queue                      ``test_school``:
                                       ``test_the_pending_queue_is_bounded_by_the_maturity_lag``;
                                       ``test_artifacts``:
                                       ``test_the_pending_queue_drained_to_nothing``
"tokens posteriores que ela nunca      ``test_grids``:
recebeu como aula" — the primary       ``test_the_primary_grid_drops_every_row_of_a_token_that_was_a_lesson``,
grid is token-disjoint (addendum 6)    ``test_the_primary_grid_is_disjoint_from_the_lesson_tokens_by_address``,
                                       ``test_the_filter_is_by_address_and_not_by_stable_id``;
                                       ``test_artifacts``:
                                       ``test_the_primary_grid_shares_no_token_with_any_lesson``
"Se a AUC do cérebro treinado subir    ``test_grids``:
... Se continuar 0,5 ou pior" — the    ``test_an_interval_entirely_above_zero_reads_as_the_registered_sentence``,
three pre-registered readings          ``test_an_interval_including_zero_reads_as_compatible_with_variation``,
(addendum 7)                           ``test_an_interval_entirely_below_zero_reads_as_the_inversion_persisting``,
                                       ``test_no_reading_ever_says_significant_or_proves``,
                                       ``test_the_three_readings_are_the_ones_the_registered_file_carries``
"Eu manteria 15 minutos ... Admission  ``test_artifacts``:
v2, encoder v2, k=8, cérebro,          ``test_nothing_but_the_teacher_moved``
decoder e horizonte ficam iguais"
the rule selector leaves the           ``test_rule``:
absolute path untouched (addendum 1)   ``test_a_configuration_with_no_rule_key_takes_the_absolute_path``,
                                       ``test_every_d10_and_d11_configuration_selects_the_absolute_rule``,
                                       ``test_the_absolute_branch_returns_exactly_what_the_execution_returns``,
                                       ``test_the_loop_refuses_the_relative_rule_rather_than_teaching_absolutely``,
                                       ``test_the_loops_default_rule_is_the_one_every_earlier_wave_took``
                                       — and every D10/D11 test, unchanged
the learning curve and the weights     ``test_school``:
(addendum 8)                           ``test_the_checkpoint_cadence_and_the_diagnostic_cadence_are_registered``;
                                       ``test_artifacts``:
                                       ``test_the_learning_curve_is_sampled_every_five_hundred_lessons``,
                                       ``test_the_weight_diagnostic_is_sampled_with_it``
the six inconclusive conditions        ``test_grids``:
(addendum 9)                           ``test_the_six_conditions_are_verbatim_from_the_registered_file``,
                                       ``test_the_thresholds_named_in_the_conditions_are_the_registered_ones``;
                                       ``test_artifacts``:
                                       ``test_every_condition_was_evaluated_and_none_was_loosened``
determinism: 100 ticks twice           ``test_artifacts``:
(addendum 10)                          ``test_the_first_hundred_ticks_reproduce_exactly``
the frozen loop branches               ``test_artifacts``:
(addendum 11)                          ``test_both_frozen_branches_left_their_digest_unchanged``
LESSON records (addendum 12)           ``test_artifacts``:
                                       ``test_every_lesson_record_carries_the_registered_fields``
the reuse of d11-001's grid, checked   ``test_artifacts``:
on >= 200 rows (addendum 1)            ``test_the_reused_reference_scores_reproduce_exactly``
"Não considero livre ainda" (PONS)     not touched by this wave; asserted by the
and the wallet features                close's empty diff, and stated in the report
no RPC, no live hour, no real money    ``test_hygiene``:
(addendum 1, 13)                       ``test_no_d12_script_imports_the_rpc_client``,
                                       ``test_no_d12_script_names_a_network_verb``,
                                       ``test_no_d12_script_imports_the_d11_runner_whose_live_path_has_a_client``,
                                       ``test_the_registration_says_zero_rpc_and_no_live_hour``
register-then-compute (addendum 4)     ``test_hygiene``:
                                       ``test_the_plan_and_the_registration_exist_and_name_the_step``,
                                       ``test_the_registration_forbids_moving_anything_after_a_result``,
                                       ``test_the_plan_registers_the_rule_the_grids_and_the_conditions``,
                                       ``test_the_plan_registers_the_ceiling_property_before_the_run``
===================================== =========================================

``test_artifacts.py`` reads what the run wrote and therefore ships **with** the
run, not with the code: a neural number may not exist before step (iii), so a
test that asserts one cannot be committed before it.
"""
