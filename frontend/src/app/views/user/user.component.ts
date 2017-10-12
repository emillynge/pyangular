import { Component, OnInit } from '@angular/core';
import {UserService, Profile, Role} from "../../user/user.service";
import {FormBuilder, FormGroup} from '@angular/forms'
import gql from "graphql-tag";
import {Logger} from "@nsalaun/ng-logger";
import {browser} from "protractor";
import {isNull, isUndefined} from "util";

function sleep(ms = 0) {
  return new Promise(r => setTimeout(r, ms));
}

@Component({
  selector: 'app-user',
  template: `
    <mat-card>
      <mat-card-title>Account Information</mat-card-title>
      
      <div *ngIf="formReady()" >
      <form  (ngSubmit)="onSubmit(form)" [formGroup]="form" >
        <mat-input-container>
          <input matInput placeholder="Name" type="text" formControlName="name">
        </mat-input-container>
        
        <mat-input-container>
          <input matInput placeholder="Email" type="text" formControlName="email">
        </mat-input-container>
        <mat-input-container matTooltip="{{editRole().description}}">
          <input matInput placeholder="Role" value="{{editRole().name}}" disabled>
        </mat-input-container>
      <button *ngIf="profileChanged() == 1"  mat-raised-button type="submit">
        Save
      </button>
      <button *ngIf="profileChanged() == 0"  disabled mat-button>
        Save
      </button>
      </form>

      </div>
    </mat-card>`,
  styles: [],
})
export class UserComponent implements OnInit {
  constructor(protected userService: UserService,
              private _logger: Logger,
              private fb: FormBuilder) {
    this.resetForm();
  }
  form: FormGroup;

  private resetFormwithProfile(profile: Profile){
    this._logger.debug("Resetting form with:");
    this._logger.debug(profile);
    this.form = this.fb.group({
      name: profile.name,
      email: profile.email,
      role: profile.role,
      gid: profile.gid,
    })
  }

  public resetForm(){
    this._logger.debug("Resetting form");
    if (isUndefined(this.userService.profile)){
      this._logger.debug(`Wait for future ${this.userService.profileFuture}`);
      this.userService.profileFuture.subscribe(value => this.resetFormwithProfile(value));
    } else {
      this._logger.debug("Reset immediately");
      this.resetFormwithProfile(this.userService.profile);
    }
  }

  ngOnInit() {
    this.resetForm();
  }

  formReady(): boolean{
    return !isUndefined(this.form)
  }

  static valueChanged(a, b): boolean {
    if (isNull(b)){
      if (a == ""){return false}
      if (isNull(a)) {return false}
    }
    return a != b
  }
  onSubmit(form: FormGroup){
    this.userService.updateUserInfo(form.value).subscribe(value => {
      this.resetForm();
    })
  }
  profileChanged(): number{
    if (this.form.value.email != this.userService.profile.email){
      return 1
    }
    if (UserComponent.valueChanged(this.form.value.name, this.userService.profile.name)){
      return 1
    }
    return 0
  }

  editRole(): Role {
    return this.userService.roles.get(this.form.value.role)
  }

}