import threading

try:
    import queue
except ImportError:
    import Queue as queue


# Background worker
class Worker(threading.Thread):
    def __init__(self):
        super(Worker, self).__init__()
        self.jobs = queue.Queue()

    def run(self):
        while True:
            name, fn, args, kwargs = self.jobs.get()
            try:
                fn(*args, **kwargs)
            except Exception as e:
                log('worker: job {0} fails with {1}'.format(name, e), log_debug)

    def async(self, name, fn, *args, **kwargs):
        self.jobs.put((name, fn, args, kwargs))

worker = None


def run_async(name, fn, *args, **kwargs):
    global worker
    if not worker:
        worker = Worker()
        worker.start()
    worker.async(name, fn, *args, **kwargs)
