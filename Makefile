autobuild-dev:
	cd frontend && ng build --output-path ../backend/js/ -e dev --watch --sourcemaps true

build.prod:
	cd frontend && ng build --output-path ../backend/js/ -e prod --aot