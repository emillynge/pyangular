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
    <md-card>
      <md-card-title>Account Information</md-card-title>
      
      <div *ngIf="formReady()" >
      <form  (ngSubmit)="onSubmit(form)" [formGroup]="form" >
        <md-input-container>
          <input mdInput placeholder="Name" type="text" formControlName="name">
        </md-input-container>
        
        <md-input-container>
          <input mdInput placeholder="Email" type="text" formControlName="email">
        </md-input-container>
        <md-input-container mdTooltip="{{editRole().description}}">
          <input mdInput placeholder="Role" value="{{editRole().name}}">
        </md-input-container>
      <button *ngIf="profileChanged() == 1"  md-raised-button type="submit">
        Save
      </button>
      <button *ngIf="profileChanged() == 0"  disabled md-button>
        Save
      </button>
      </form>

      </div>
    </md-card>`,
  styles: [],
})
export class UserComponent implements OnInit {
  constructor(protected userService: UserService,
              private _logger: Logger,
              private fb: FormBuilder) {
    this.resetForm();
  }
  form: FormGroup;

  public resetForm(){
    this._logger.debug("profile name at init");
    if (isUndefined(this.userService.profile)){
      sleep(100).then(value => this.resetForm())
    } else {
      this._logger.debug(this.userService.profile.name);

      this.form = this.fb.group({
        name: this.userService.profile.name,
        email: this.userService.profile.email,
        role: this.userService.profile.role,
        gid: this.userService.profile.gid,
      })
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
