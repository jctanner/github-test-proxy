lint:
	pylint github_proxy

test:
	find . -name '*.pyc' -exec rm --force {} +
	find . -name '__pycache__' -exec rm -r --force {} +
	python -m pytest --capture=no tests
