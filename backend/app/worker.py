from app.db.session import Base, engine
from app.services.jobs import worker_loop
if __name__=='__main__':
    Base.metadata.create_all(bind=engine)
    worker_loop()
