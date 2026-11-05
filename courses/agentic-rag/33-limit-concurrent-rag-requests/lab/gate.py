"""One-event-loop FIFO admission. A lease represents actual unfinished work."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
class Refused(Exception):pass
class Gate:
    def __init__(self,max_active=1,max_waiting=1,wait_seconds=0.15):
        if any(type(x) is not int or not 1<=x<=32 for x in (max_active,)) or type(max_waiting) is not int or not 0<=max_waiting<=32:raise ValueError('invalid_capacity')
        if type(wait_seconds) not in (int,float) or not 0<wait_seconds<=30:raise ValueError('invalid_wait_deadline')
        self.max_active=max_active;self.max_waiting=max_waiting;self.wait_seconds=wait_seconds
        self.active=0;self.waiters=deque();self.events=deque(maxlen=128);self.sequence=0
    def event(self,status):
        self.sequence+=1;self.events.append({'order':self.sequence,'status':status,'active':self.active,'waiting':len(self.waiters)})
    def snapshot(self):return {'active':self.active,'waiting':len(self.waiters),'events':list(self.events),'max_active':self.max_active,'max_waiting':self.max_waiting,'wait_seconds':self.wait_seconds}
    async def acquire(self):
        if self.active<self.max_active and not self.waiters:
            self.active+=1;self.event('admitted');return
        if len(self.waiters)>=self.max_waiting:
            self.event('queue_full');raise Refused('queue_full')
        future=asyncio.get_running_loop().create_future();self.waiters.append(future);self.event('queued')
        try:await asyncio.wait_for(asyncio.shield(future),self.wait_seconds)
        except (TimeoutError,asyncio.CancelledError) as error:
            if future in self.waiters:self.waiters.remove(future)
            elif future.done() and not future.cancelled():self.release()
            self.event('wait_timeout' if isinstance(error,TimeoutError) else 'wait_cancelled')
            if isinstance(error,TimeoutError):raise Refused('wait_timeout') from None
            raise
    def release(self):
        if self.active<=0:raise RuntimeError('unbalanced_release')
        self.active-=1;self.event('released')
        if self.waiters:
            future=self.waiters.popleft();self.active+=1;future.set_result(None);self.event('promoted')
    @asynccontextmanager
    async def lease(self):
        await self.acquire()
        try:yield
        finally:self.release()

async def finish_worker(call,*args):
    """Cancellation cannot free capacity while an uncancellable thread still runs."""
    task=asyncio.create_task(asyncio.to_thread(call,*args));cancelled=False
    while not task.done():
        try:await asyncio.shield(task)
        except asyncio.CancelledError:cancelled=True
        except Exception:break
    if cancelled:
        # Consume a possible worker exception before propagating cancellation.
        if not task.cancelled():task.exception()
        raise asyncio.CancelledError
    return task.result()
