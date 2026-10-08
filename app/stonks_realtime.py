"""Bounded scoped server push. Market data is public; broker state is scoped."""
import json,queue,threading,time
from copy import deepcopy

class StonksRealtimeBus:
    def __init__(self):self.lock=threading.RLock();self.listeners={};self.latest={};self.observers={}
    def publish(self,scope,event,data):
        payload={'type':event,'data':deepcopy(data),'timestamp':time.time(),'zero_tokens':True}
        with self.lock:
            self.latest.setdefault(scope,{})[event+':'+str(data.get('symbol',''))]=payload
            targets=[q for owner,q in self.listeners.values() if scope=='MARKET_PUBLIC' or owner==scope]
        for target in targets:
            try:target.put_nowait(payload)
            except queue.Full:
                try:target.get_nowait();target.put_nowait(payload)
                except (queue.Empty,queue.Full):pass
    def subscribe(self,scope):
        with self.lock:
            if len(self.listeners)>=2:raise ValueError('Límite de streams: usa snapshot incremental temporalmente.')
            target=queue.Queue(maxsize=32);identifier=id(target);self.listeners[identifier]=(scope,target)
            return identifier,target
    def unsubscribe(self,identifier):
        with self.lock:self.listeners.pop(identifier,None)
    def snapshot(self,scope):
        with self.lock:return deepcopy({**self.latest.get('MARKET_PUBLIC',{}),**self.latest.get(scope,{})})
    def observe(self,scope,read):
        with self.lock:
            self.observers[scope]=time.monotonic()
            key='observer:'+scope
            if key in self.observers:return
            self.observers[key]=True
        def worker():
            previous=None
            try:
                while time.monotonic()-self.observers.get(scope,0)<75:
                    try:
                        data=read();signature=json.dumps(data,sort_keys=True,default=str)
                        if signature!=previous:self.publish(scope,'PORTFOLIO_UPDATE',data);previous=signature
                    except Exception:self.publish(scope,'FEED_STATUS',{'state':'BROKER_UNAVAILABLE','source':'Alpaca Paper','zero_tokens':True})
                    time.sleep(20)
            finally:
                with self.lock:self.observers.pop(key,None)
        threading.Thread(target=worker,daemon=True).start()

BUS=StonksRealtimeBus()
