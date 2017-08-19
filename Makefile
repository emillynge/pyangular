TS_LIBS = --lib DOM,ES6,DOM.Iterable,ScriptHost,ESNext
DEF_CMD = grep 'name: \"lib\"' frontend/node_modules/typescript/lib/typescript.js -A99 | grep 'lib\.' | awk '{ print \$$1 }' | sed -E 's|([^:]+):|\1,|'

autobuild-dev:
	cd frontend && ng build --output-path ../backend/js/ -e dev --watch --sourcemaps true

build.prod:
	cd frontend && ng build --output-path ../backend/js/ -e prod --aot

print-def-libs:
	bash -c "$(DEF_CMD)"

npm-update:
	cd frontend && npm update