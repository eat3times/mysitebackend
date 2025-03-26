from celery import Celery

celery_app = Celery(
    "trading",
    broker="redis://localhost:6379/0",
    include=["app.trade"]
)

celery_app.conf.update(
    result_expires=3600,
    task_acks_late=False,
    task_reject_on_worker_lost=True,
    task_ignore_result=False,
    task_track_started=True,
    # worker_pool='prefork'  # 기본값이라 생략 가능
)

if __name__ == "__main__":
    celery_app.start()
