import pytest

from tests.implementations import implementations


@pytest.fixture(params=implementations)
def router(request):
    impl = request.param

    app, router, settings = impl()
    kwargs = {**settings[0], **dict(prefix=None)}
    router = router(**kwargs)

    yield router


def test_prefix_lowercase(router):
    assert type(router.prefix) is str
    assert router.prefix != ''
    assert router.prefix == router.prefix.lower()
