import threading

from spotify_helper.jobs import Jobs


def wait(job):
    for _ in range(200):
        if job.finished:
            return
        threading.Event().wait(0.01)


def test_job_reports_progress_and_result():
    jobs = Jobs()

    def work(progress):
        for i in range(3):
            progress(i + 1, 3)
        return "ok"

    job = jobs.get(jobs.start("scan", work))
    wait(job)
    assert (job.done, job.total, job.result, job.error, job.label) == (3, 3, "ok", None, "scan")


def test_job_captures_errors():
    jobs = Jobs()

    def boom(progress):
        raise RuntimeError("Last.fm is down")

    job = jobs.get(jobs.start("scan", boom))
    wait(job)
    assert job.finished and job.error == "Last.fm is down"
