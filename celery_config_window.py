from celery import Celery
import multiprocessing

celery_app = Celery(
    "trading",
    broker="redis://localhost:6379/0",  # Redis 브로커 사용
    backend="redis://localhost:6379/0",  # 결과 저장소
    include=["app.trade"]  # 작업이 들어갈 파일 등록
)

celery_app.conf.update(
    result_expires=3600,  # 작업 결과 유지 시간 (1시간)
    
    # ✅ 중복 실행 방지 관련 설정
    task_acks_late=False,  # 실패한 작업을 다시 실행하지 않도록 설정
    task_reject_on_worker_lost=True,  # 워커가 중단될 경우 작업을 다시 실행하지 않음
    task_ignore_result=True,  # 결과를 저장하지 않아 불필요한 중복 실행 방지
    
    task_track_started=True,  # 작업 시작 상태 추적
    worker_pool='solo',  # Windows 환경에서 안정적인 실행을 위해 solo 모드 사용
)

def main():
    multiprocessing.set_start_method('spawn')  # Windows에서 spawn 방식 지정
    celery_app.start()

if __name__ == "__main__":
    main()
