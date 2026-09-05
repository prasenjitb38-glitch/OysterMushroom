_subscribers=[]
def subscribe(callback):
    if callback not in _subscribers:_subscribers.append(callback)
def unsubscribe(callback):
    if callback in _subscribers:_subscribers.remove(callback)
def publish(event="data_changed"):
    for callback in tuple(_subscribers):callback(event)
