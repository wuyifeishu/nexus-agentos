#!/bin/bash
set -e
echo '=== TestPyPI v1.16.37 ==='
sed -i 's/version = "[0-9.]*"/version = "1.16.37"/' pyproject.toml
sed -i 's/__version__ = "[0-9.]*"/__version__ = "1.16.37"/' agentos/__init__.py
rm -rf dist && python -m build --wheel --sdist --no-isolation > /dev/null 2>&1
/home/marvis/.local/bin/twine upload --non-interactive -u __token__ -p pypi-AgENdGVzdC5weXBpLm9yZwIkYWQ1NTBiYTMtNDI4Ni00ZjllLTk4YmUtNDA4OWQyMjg1ZjNiAAIqWzMsIjIyOWVhNDJkLTE4NGMtNDQ2NS04YzE3LTA5Yjk2NjcwOWFjNCJdAAAGIMcsDcT-gg7L7yz0nojSzJYJuacq0xJ9fBCi-w-gowDN --repository-url https://test.pypi.org/legacy/ dist/*
echo '=== TestPyPI v1.16.38 ==='
sed -i 's/version = "[0-9.]*"/version = "1.16.38"/' pyproject.toml
sed -i 's/__version__ = "[0-9.]*"/__version__ = "1.16.38"/' agentos/__init__.py
rm -rf dist && python -m build --wheel --sdist --no-isolation > /dev/null 2>&1
/home/marvis/.local/bin/twine upload --non-interactive -u __token__ -p pypi-AgENdGVzdC5weXBpLm9yZwIkYWQ1NTBiYTMtNDI4Ni00ZjllLTk4YmUtNDA4OWQyMjg1ZjNiAAIqWzMsIjIyOWVhNDJkLTE4NGMtNDQ2NS04YzE3LTA5Yjk2NjcwOWFjNCJdAAAGIMcsDcT-gg7L7yz0nojSzJYJuacq0xJ9fBCi-w-gowDN --repository-url https://test.pypi.org/legacy/ dist/*
echo '=== TestPyPI v1.16.39 ==='
sed -i 's/version = "[0-9.]*"/version = "1.16.39"/' pyproject.toml
sed -i 's/__version__ = "[0-9.]*"/__version__ = "1.16.39"/' agentos/__init__.py
rm -rf dist && python -m build --wheel --sdist --no-isolation > /dev/null 2>&1
/home/marvis/.local/bin/twine upload --non-interactive -u __token__ -p pypi-AgENdGVzdC5weXBpLm9yZwIkYWQ1NTBiYTMtNDI4Ni00ZjllLTk4YmUtNDA4OWQyMjg1ZjNiAAIqWzMsIjIyOWVhNDJkLTE4NGMtNDQ2NS04YzE3LTA5Yjk2NjcwOWFjNCJdAAAGIMcsDcT-gg7L7yz0nojSzJYJuacq0xJ9fBCi-w-gowDN --repository-url https://test.pypi.org/legacy/ dist/*
echo '=== TestPyPI v1.16.40 ==='
sed -i 's/version = "[0-9.]*"/version = "1.16.40"/' pyproject.toml
sed -i 's/__version__ = "[0-9.]*"/__version__ = "1.16.40"/' agentos/__init__.py
rm -rf dist && python -m build --wheel --sdist --no-isolation > /dev/null 2>&1
/home/marvis/.local/bin/twine upload --non-interactive -u __token__ -p pypi-AgENdGVzdC5weXBpLm9yZwIkYWQ1NTBiYTMtNDI4Ni00ZjllLTk4YmUtNDA4OWQyMjg1ZjNiAAIqWzMsIjIyOWVhNDJkLTE4NGMtNDQ2NS04YzE3LTA5Yjk2NjcwOWFjNCJdAAAGIMcsDcT-gg7L7yz0nojSzJYJuacq0xJ9fBCi-w-gowDN --repository-url https://test.pypi.org/legacy/ dist/*
sed -i 's/version = "[0-9.]*"/version = "1.16.40"/' pyproject.toml
sed -i 's/__version__ = "[0-9.]*"/__version__ = "1.16.40"/' agentos/__init__.py
echo 'ALL TestPyPI DONE'
