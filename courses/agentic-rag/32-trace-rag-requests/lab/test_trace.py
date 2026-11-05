import asyncio,json,threading,unittest
from recorder import Recorder,current_trace
from traced import traced_retrieve
from service import RetrieveRequest
from tools import load_snapshot

class TraceTests(unittest.IsolatedAsyncioTestCase):
    def test_fixed_fields_redact_inputs_and_errors(self):
        r=Recorder()
        with r.request():
            try:
                with r.span('search'):raise RuntimeError('SECRET question paragraph credential')
            except RuntimeError:pass
        raw=json.dumps(r.snapshot());self.assertNotIn('SECRET',raw)
        for rows in r.snapshot().values():
            for row in rows:self.assertEqual(set(row),{'trace_id','span_id','parent_span_id','order','name','status'});self.assertLessEqual(len(json.dumps(row).encode()),320)
        self.assertIsNone(current_trace.get())
    async def test_concurrent_context_and_parent_isolation(self):
        r=Recorder()
        async def work():
            with r.request() as tid:
                await asyncio.to_thread(lambda:child(r))
                return tid
        def child(r):
            with r.span('read'):pass
        ids=await asyncio.gather(work(),work());self.assertNotEqual(*ids)
        for tid,rows in r.snapshot().items():
            self.assertEqual([row['order'] for row in rows],[1,2]);self.assertEqual(rows[1]['parent_span_id'],rows[0]['span_id']);self.assertTrue(all(row['trace_id']==tid for row in rows))
    async def test_active_eviction_does_not_interrupt_work(self):
        r=Recorder(max_traces=1);started=asyncio.Event();release=asyncio.Event()
        async def first():
            with r.request():
                started.set();await release.wait()
                with r.span('read'):pass
                r.mark_response(200)
        t=asyncio.create_task(first());await started.wait()
        with r.request():pass
        release.set();await t
        self.assertEqual(len(r.snapshot()),1);self.assertEqual(r.stats()['dropped_traces'],1);self.assertEqual(r.stats()['dropped_spans'],1)
    def test_span_capacity_drops_without_breaking_retrieval(self):
        r=Recorder(max_spans=1)
        with r.request():
            with r.span('search'):pass
        self.assertEqual(len(next(iter(r.snapshot().values()))),1);self.assertEqual(r.stats()['dropped_spans'],1)
    def test_unknown_span_fields_fail_closed(self):
        r=Recorder()
        with r.request():
            with self.assertRaises(ValueError):
                with r.span('raw question'):pass
    def test_real_retrieval_admission_and_tools(self):
        r=Recorder()
        with r.request():code,body=traced_retrieve(RetrieveRequest(question='Will write_text replace an existing file?'),load_snapshot(),r)
        names=[row['name'] for row in next(iter(r.snapshot().values()))]
        self.assertEqual(code,200);self.assertIn('search',names);self.assertIn('read',names)
        for i,name in enumerate(names):
            if name in ('search','read'):self.assertEqual(names[i-1],'admission')
        self.assertNotEqual(next(iter(r.snapshot())),body['request_id'])
    def test_retention_and_invalid_limits(self):
        r=Recorder(max_traces=1)
        for _ in range(3):
            with r.request():pass
        self.assertEqual(len(r.snapshot()),1);self.assertEqual(r.stats()['dropped_traces'],2)
        with self.assertRaises(ValueError):Recorder(max_traces=True)
if __name__=='__main__':unittest.main()
