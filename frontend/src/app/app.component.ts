import { Component } from '@angular/core';
import { UserService, Role } from "./user/user.service";
import {MatIconRegistry} from "@angular/material";
import {DomSanitizer} from "@angular/platform-browser";
import {Router} from "@angular/router";
import {environment } from "../environments/environment"


@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css'],
  viewProviders: [MatIconRegistry],
})

export class AppComponent {
  title = environment.applicationName;
  signedIn = false;
  public us: UserService;

  constructor(private userService: UserService,
              iconReg: MatIconRegistry,
              sanitizer: DomSanitizer,
              private router: Router,
              ) {
    iconReg.addSvgIcon('login', sanitizer.bypassSecurityTrustResourceUrl('/assets/login.svg'))
      .addSvgIcon('logout', sanitizer.bypassSecurityTrustResourceUrl('/assets/logout.svg'))
      .addSvgIcon('account-switch', sanitizer.bypassSecurityTrustResourceUrl('/assets/account-switch.svg'));
    this.signedIn = this.isSignedIn();
    this.us = this.userService
  }

  gotoUser(): void {
    this.router.navigate(['/user'])
  }

  signIn(): void {
    this.userService.signIn();
    this.signedIn = true;
  }

  switchAccount(): void {
    this.userService.switchAccount();
  }

  signOut(): void {
    this.userService.signOut();
    this.signedIn = false;
  }
  isSignedIn(): boolean {
    return UserService.isUserSignedIn();
  }


}
