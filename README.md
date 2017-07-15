# PyAngular web application skeleton

This project was made to serve as a reuseable skeleton for web-application projects.

It comes with a lot of technology presets:

* Angular4 for frontend
* Python for backend
    * Note that the python backend not only serves as API, but also _serves_ the javascrip application bundle! No need to set up an NGINX just to serve files.
* Backend uses `asyncio` for all libraries, going as far as monkeypatching/subclassing existing libraries to become non-blocking
* Google account for authentication. The user just need to log in with their google account to be authenticated. 
    * I usually rely heavily on google services anyways which requires user to grant permission to access drive/calendar etc.
    * Web tokens are obtained by frontend and forwarded to backend with all calls to the API. Tokens are verified in backend. No need to manage creation of session token etc.
* Google Datastore for database-as-a-service.
* GraphQL + Graphene + aiohttp for backend API. GraphQL especially has a slightly nasty learning curve, but I wanted something other than REST.
* All settings managed by environment variables and environment files.

## Setting up a project.

### Name your project
In this section I will use APPID in place of the name you choose for your project.
If I use "*" in a file name, it is because there may be several files that I want to refer to.

Clone the repository: `git clone https://github.com/emillynge/pyangular.git APPID`

Change the default project name in:
* `backend/.app.env`
* `frontend/environments*.ts`

#### Make your own github repo
Make a new repository (I wouldn't recommend a fork, as you are not going to be pushing back to the skeleton project.) called APPID.
Rename the current remote  "origin" (pointing to emillynge/pyangular) to upstream, and add your own repo as the new origin.
```
git remote rename origin upstream
git remote add origin https://YOURACCOUNT/APPID.git 
```

### Google Credentials
Create a google project at  [https://console.developers.google.com/projectcreate]()

Set up a service account [https://console.developers.google.com/apis/credentials/serviceaccountkey]()
Set up a Oauth client ID [https://console.developers.google.com/apis/credentials/oauthclient]()

Download credentials for both, save service account creds as `backend/client_sercret.json` and Oauth creds at `backend/webapp_client_secret.json`.

If you choose other locations, change `backend/.test.env` accordingly.

Enable Google Datatore API for your project.


