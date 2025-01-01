import pytest
import shutil


@pytest.fixture(scope="session")
def counter():
    def _counter():
        count = 1
        while True:
            yield count
            count += 1

    return _counter()


@pytest.fixture
def temp_directory(tmp_path, counter):
    dir = tmp_path / f"test_dir{next(counter)}"
    dir.mkdir(exist_ok=True, parents=True)
    yield dir

    if dir.exists():
        shutil.rmtree(dir)


@pytest.fixture(autouse=True)
def patch_logger(mocker):
    mocker.patch("utils.logger")
    mocker.patch("waiter.logger")
