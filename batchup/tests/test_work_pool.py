import pytest
import os
import numpy as np


# Define example task function in the root of the module so that pickle can
# find it
def _example_task_fn(*args):
    return sum(args), os.getpid()


# Define example batch extractor function in the root of the module so that
# pickle can find it
class _AbstractExampleBatchIterator (object):
    def __init__(self, N):
        self.N = N

    # Define __len__ here to save us some work in the base classes that we
    # will actually use
    def __len__(self):
        return self.N


class _ExampleBatchIteratorIdentity (_AbstractExampleBatchIterator):
    def __getitem__(self, indices):
        return indices


class _ExampleBatchIteratorSquare (_AbstractExampleBatchIterator):
    def __getitem__(self, indices):
        return indices**2


class _ExampleBatchIteratorError (_AbstractExampleBatchIterator):
    def __getitem__(self, indices):
        raise ValueError


@pytest.fixture
def pool():
    from batchup import work_pool
    return work_pool.WorkerPool(processes=5)


def test_work_stream(pool):
    def task_generator():
        for i in range(500):
            yield _example_task_fn, (i, i, i)

    stream = pool.work_stream(task_generator())

    pids = set()
    for i in range(500):
        v, pid = stream.retrieve()
        pids.add(pid)
        assert v == i * 3

    assert len(pids) == 5

    # Check that one last call to retrieve returns None
    assert stream.retrieve() is None


def test_parallel_data_source(pool):
    from batchup import data_source

    ds = data_source.ArrayDataSource(
        [_ExampleBatchIteratorIdentity(100),
         _ExampleBatchIteratorSquare(100)]
    )

    pds = pool.parallel_data_source(ds)

    # Check number of samples
    assert ds.num_samples() == 100
    assert pds.num_samples() == 100

    # Arrays of flags indicating which numbers we got back
    n_flags = np.zeros((100,), dtype=bool)
    n_sqr_flags = np.zeros((10000,), dtype=bool)

    BATCHSIZE = 10

    for batch in pds.batch_iterator(
            batch_size=BATCHSIZE, shuffle=np.random.RandomState(12345)):
        # batch should be a list
        assert isinstance(batch, list)
        # batch should contain two arrays
        assert len(batch) == 2
        # each array should be of length BATCHSIZE
        assert batch[0].shape[0] == BATCHSIZE
        assert batch[1].shape[0] == BATCHSIZE

        # Check off the numbers we got back
        n_flags[batch[0]] = True
        n_sqr_flags[batch[1]] = True

    # Check the flags arrays
    assert n_flags.sum() == 100
    assert n_sqr_flags.sum() == 100

    expected_n_flags = np.ones((100,), dtype=bool)
    expected_n_sqr_flags = np.zeros((10000,), dtype=bool)
    expected_n_sqr_flags[np.arange(100)**2] = True
    assert (n_flags == expected_n_flags).all()
    assert (n_sqr_flags == expected_n_sqr_flags).all()

    # Check that passing something that isn't a data source fails
    with pytest.raises(TypeError):
        pool.parallel_data_source(_ExampleBatchIteratorIdentity(100))

    # Check that passing a non random access data source fails
    with pytest.raises(TypeError):
        def make_batch_iter(**kwargs):
            def batch_iterator(batch_size):
                for i in range(0, 100, batch_size):
                    yield np.random.normal(size=(batch_size, 2))
        cds = data_source.CallableDataSource(make_batch_iter)

        pool.parallel_data_source(cds)

    # Check that errors raised by data sources are passed back
    eds = data_source.ArrayDataSource([_ExampleBatchIteratorError(100)])
    peds = pool.parallel_data_source(eds)
    peds_iter = peds.batch_iterator(batch_size=BATCHSIZE,
                                    shuffle=np.random.RandomState(12345))
    with pytest.raises(ValueError):
        next(peds_iter)
