import asyncio,threading,unittest
from gate import Gate,Refused,finish_worker
class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_before_invocation(self):
        g=Gate(max_waiting=0);called=[]
        async with g.lease():
            with self.assertRaisesRegex(Refused,'queue_full'):
                async with g.lease():called.append(1)
        self.assertEqual(called,[]);self.assertEqual(g.active,0)
    async def test_wait_deadline_removes_waiter(self):
        g=Gate(wait_seconds=.01)
        async with g.lease():
            with self.assertRaisesRegex(Refused,'wait_timeout'):await g.acquire()
            self.assertEqual(len(g.waiters),0)
        self.assertEqual(g.active,0)
    async def test_fifo_and_capacity(self):
        g=Gate(max_waiting=2,wait_seconds=1);order=[]
        await g.acquire()
        async def work(i):
            async with g.lease():order.append(i);await asyncio.sleep(0)
        a=asyncio.create_task(work(1));await asyncio.sleep(0);b=asyncio.create_task(work(2));await asyncio.sleep(0)
        self.assertEqual(len(g.waiters),2);g.release();await asyncio.gather(a,b)
        self.assertEqual(order,[1,2]);self.assertTrue(all(e['active']<=1 for e in g.events));self.assertEqual(g.active,0)
    async def test_queued_cancel_removes_waiter(self):
        g=Gate();await g.acquire();t=asyncio.create_task(g.acquire());await asyncio.sleep(0);t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
        self.assertEqual(len(g.waiters),0);g.release();self.assertEqual(g.active,0)
    async def test_cancelled_worker_holds_lease_until_thread_finishes(self):
        g=Gate();started=threading.Event();release=threading.Event()
        def worker():started.set();release.wait(2)
        async def work():
            async with g.lease():await finish_worker(worker)
        t=asyncio.create_task(work());await asyncio.to_thread(started.wait,1);t.cancel();await asyncio.sleep(.01)
        self.assertEqual(g.active,1);self.assertFalse(t.done());release.set()
        with self.assertRaises(asyncio.CancelledError):await t
        self.assertEqual(g.active,0)
    async def test_worker_exception_releases_lease(self):
        g=Gate()
        def broken():raise RuntimeError('broken')
        with self.assertRaises(RuntimeError):
            async with g.lease():await finish_worker(broken)
        self.assertEqual(g.active,0)
    def test_invalid_config(self):
        for kw in [{'max_active':True},{'max_waiting':-1},{'wait_seconds':float('nan')}]:
            with self.assertRaises(ValueError):Gate(**kw)
if __name__=='__main__':unittest.main()
