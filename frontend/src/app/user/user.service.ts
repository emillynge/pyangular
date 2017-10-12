import { Injectable } from '@angular/core';
import {GoogleApiConfig, GoogleApiModule, GoogleApiService, GoogleAuthService} from "ng-gapi";
import AuthorizeResponse = gapi.auth2.AuthorizeResponse
import GoogleUser = gapi.auth2.GoogleUser;
import * as _ from "lodash";
import {isNullOrUndefined, isUndefined} from "util";
import { Logger } from '@nsalaun/ng-logger';
import { Http, Response, URLSearchParams } from '@angular/http';
import { Apollo } from 'apollo-angular';
import gql from 'graphql-tag';
import {AsyncSubject} from "rxjs/AsyncSubject";
import { environment } from '../../environments/environment';

export interface Profile {
  gid: string;
  name: string;
  email: string;
  role: number;
}


interface QueryResponse {
  currentProfile: Profile;
}



const ProfileQuery = gql`
  query currentProfile{
    currentProfile{
      gid
      name
      email
      role
    }
  }
`;


const ProfileUpdate = gql`
  mutation profileUpdate($gid: String!, $name: String!, $email: String! $role: Int!) {
    profileUpdate(gid: $gid, name: $name, email: $email, role: $role) {
      user {
      gid
      name
      email
      role
    }
      ok
    }
  }
`;

const TokenRefresh = gql`
mutation tokenRefresh($code: String!) {
  tokenRefresh(code: $code) {
    user {
      gid
      name
      email
      role
      }
      ok
    }
  }
`

interface updateProfileResponse {
  profileUpdate: {ok: boolean, user: Profile};
}

export type Role = { name: string, description: string, accessLevel: number };


@Injectable()
export class UserService {
  public gUser: GoogleUser;
  public profile: Profile;
  public role: Role;
  private gapiLoaded: boolean = false;
  private adminRole: Role = {name: "admin", description: "Highest level", accessLevel: 10};
  private registeredRole: Role = {name: "registered", description: "A gUser that is registered", accessLevel: 5};
  private unregisteredRole: Role = {name: "unregistered", description: "A gUser that is not registered in the system", accessLevel: 1};
  private signedOutRole: Role = {name: "signedout", description: "A gUser that is not not signed in to the application", accessLevel: 0};
  private gapiNotLoadedRole: Role = {name: "unknown", description: "Role of gUser cannot be determined yet", accessLevel: -1};
  public roles: Map<number, Role> = new  Map<number, Role>();
  public profileFuture: AsyncSubject<Profile>;

  constructor(private googleAuth: GoogleAuthService,
              private gapiService: GoogleApiService,
              private apollo: Apollo,
              private _logger: Logger) {
    this.addRole(this.adminRole);
    this.addRole(this.registeredRole);
    this.addRole(this.unregisteredRole);
    this.addRole(this.signedOutRole);
    this.addRole(this.gapiNotLoadedRole);

    this.role = this.gapiNotLoadedRole;

    this.profileFuture = new AsyncSubject();
    gapiService.onLoad(()=> {

      this.gapiLoaded = true;
      this.googleAuth.getAuth()
        .subscribe((auth) => {
          this.signInListener(auth.isSignedIn.get());
          auth.isSignedIn.listen(isSignedIn => this.signInListener(isSignedIn));
        });
    });

  }
  private addRole(role: Role){
    this.roles.set(role.accessLevel, role)
  }

  private signInListener(isSignedIn: boolean){
    this._logger.debug(`signin change: ${isSignedIn}`);

    if (isSignedIn){
      this._logger.debug("setting gUser");
      this.setUser();

    } else {
      this._logger.debug("unsetting gUser");
      this.gUser = undefined;
      this.role = this.signedOutRole;
    }
    this._logger.info(this.role);
  }
  private setProfile(newProfile: Profile){
    this._logger.debug("Setting new profile");
    this._logger.debug(newProfile);
    this.profileFuture.next(newProfile);
    this.profileFuture.complete();
    this._logger.debug("Future completed");
    this._logger.debug(this.profileFuture);
    this.profile = newProfile;
    this.profileFuture = new AsyncSubject();
  }

  private setUser(): void {
    if (this.gapiLoaded) {
      this._logger.debug('gAPI loaded');
      this.googleAuth.getAuth()
        .subscribe((auth) => {
          this.gUser = auth.currentUser.get();
          this.role = this.getUserRole();
          let profile = this.gUser.getBasicProfile();
          this._logger.debug('setting user info in local storage')
          let token =  this.gUser.getAuthResponse().access_token;
          let email =  profile.getEmail();
          let gid = profile.getId();
          sessionStorage.setItem('access_token', token);
          sessionStorage.setItem('email', email);
          sessionStorage.setItem('gid', gid);
          this._logger.debug(token);

          this._logger.debug('calling api');
          this.apollo.watchQuery<QueryResponse>({
            query: ProfileQuery})
            .subscribe(
              ({data}) => {
                this.setProfile(data.currentProfile);
                this.role = this.getUserRole();
              }
            );
        });
    } else {
      this._logger.debug('gAPI *not* loaded');
      this.gUser = undefined;
      this.role = this.getUserRole();
    }
  }

  public updateUserInfo(new_profile: Profile): AsyncSubject<Profile>{
    this.apollo.mutate<updateProfileResponse>({
      mutation: ProfileUpdate,
      variables: new_profile
    }).subscribe(({data})=> {
      this._logger.debug(data);
      this.setProfile(data.profileUpdate.user);
    });
    return this.profileFuture
  }
  public signIn(): void {
    this.googleAuth.getAuth()
      .subscribe((auth) => {
        auth.grantOfflineAccess({scope: environment.scope.join(" "),
        prompt: "consent"}).then((resp: AuthorizeResponse) => {
            this._logger.debug(resp.code);
            this.apollo.mutate<updateProfileResponse>({
              mutation: TokenRefresh,
              variables: {code: resp.code}
              }
            ).subscribe( ({data}) => {
                this._logger.debug(data)
              }

            )
          }
        );
      });
  }

  public signInSelect(): void {
    this.googleAuth.getAuth()
      .subscribe((auth) => {
        auth.signIn({prompt: "select_account"});
        this._logger.debug(auth.currentUser.get().getAuthResponse().access_token);
      });
  }

  public switchAccount(): void {
    this.googleAuth.getAuth()
      .subscribe((auth) => {
        auth.signOut()
          .then(() => auth.signIn({prompt: "select_account"}))
      });
  }

  public signOut(): void {
    this.googleAuth.getAuth()
      .subscribe((auth) => {
        auth.signOut().then(() => this._logger.debug('logging out'))
      });
  }

  public static isUserSignedIn(): boolean {
    return !_.isEmpty(sessionStorage.getItem('access_token'));
  }

  private signOutSuccessHandler() {
    sessionStorage.removeItem(
      'access_token'
    );
    sessionStorage.removeItem(
      'email'
    );
    sessionStorage.removeItem(
      'gid'
    );

  }


  private getUserRole() {
    if (!this.gapiLoaded) {
      return this.gapiNotLoadedRole;
    }

    if (isUndefined(this.gUser)) {
      return this.signedOutRole;
    }

    if (isNullOrUndefined(this.profile)){
      return this.unregisteredRole
    }

    return this.roles.get(this.profile.role)
  }
}
