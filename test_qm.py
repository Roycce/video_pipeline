import sys
from PySide6.QtCore import QCoreApplication
from queue_manager import QueueManager, TaskStatus
import settings

def main():
    app = QCoreApplication(sys.argv)
    qm = QueueManager()
    
    def on_task_completed(idx, success, msg):
        print(f"Task {idx} completed. Success: {success}, msg: {msg}")
        app.quit()
        
    def on_task_updated(idx):
        tasks = qm.get_tasks()
        print(f"Task {idx} updated: {tasks[idx].status}")
        
    qm.task_completed.connect(on_task_completed)
    qm.task_updated.connect(on_task_updated)
    
    qm.add_task("test_stream.mp4")
    
    s = settings.Settings()
    s.set("file_size_limit_enabled", False)
    qm.start_processing(s.get_all())
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
