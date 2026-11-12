import unittest
from diagnostics.sm_sweep.metrics import summarize_forward, sweep_order, fixed_prompt_ids, summarize_rows


class SweepTests(unittest.TestCase):
    def test_prefill_decode_separate_and_fixed_steps(self):
        r = summarize_forward([512,1,1], [20.,4.,6.], 512, 3)
        self.assertEqual(r['prefill_forward_ms'], 20)
        self.assertEqual(r['decode_forward_ms_per_token'], 5)
        self.assertEqual(r['decode_forward_total_ms'], 10)

    def test_bad_token_shapes_not_silently_accepted(self):
        for shapes in ([512,2,1], [512,1], [1,1,1]):
            with self.assertRaises(ValueError):
                summarize_forward(shapes, [1.]*len(shapes), 512, 3)

    def test_reverse_round_balances_order(self):
        a=sweep_order([8,16,24,32,40,48],0)
        b=sweep_order([8,16,24,32,40,48],1)
        self.assertEqual(a,list(reversed(b)))
        self.assertEqual(sorted(a),[8,16,24,32,40,48])

    def test_prompt_length_and_suffix_preserved(self):
        ids=fixed_prompt_ids([1,2],[9,10],list(range(100,120)),10)
        self.assertEqual(ids,[1,2,100,101,102,103,104,105,9,10])
        with self.assertRaises(ValueError):
            fixed_prompt_ids([1,2],[9,10],[],10)

    def test_aggregate_only_measured_and_not_mixed_metrics(self):
        rows=[{'sm_count':8,'warmup':False,'prefill_forward_ms':2.}, {'sm_count':8,'warmup':False,'prefill_forward_ms':4.}, {'sm_count':8,'warmup':True,'prefill_forward_ms':100.}]
        r=summarize_rows(rows,['prefill_forward_ms'])
        self.assertEqual(r[0]['prefill_forward_ms']['n'],2)
        self.assertEqual(r[0]['prefill_forward_ms']['mean'],3)
        self.assertEqual(r[0]['prefill_forward_ms']['std'],1)

class ObserverTests(unittest.TestCase):
    def test_stream_mismatch_rejected(self):
        from diagnostics.sm_sweep.observer import check_stream
        with self.assertRaises(RuntimeError):
            check_stream(5,6)
        check_stream(5,5)

class DispatchTests(unittest.TestCase):
    def test_check_selected_native_implementation_not_dispatcher_module(self):
        from types import SimpleNamespace
        from diagnostics.sm_sweep.dispatch import native_bindings
        def wrap(implementation):
            def dispatcher(*args,**kwargs):
                return implementation(*args,**kwargs)
            return dispatcher
        def native():
            pass
        native.__module__='fla.ops.gated_delta_rule'
        def conv():
            pass
        conv.__module__='causal_conv1d.causal_conv1d_interface'
        fake=SimpleNamespace(causal_conv1d_fn=wrap(conv),causal_conv1d_update=wrap(conv),torch_chunk_gated_delta_rule=wrap(native),torch_recurrent_gated_delta_rule=wrap(native))
        bindings=native_bindings(fake)
        self.assertTrue(bindings['torch_chunk_gated_delta_rule'].startswith('fla.'))
        native.__module__='transformers.fallback'
        with self.assertRaises(RuntimeError):
            native_bindings(fake)
