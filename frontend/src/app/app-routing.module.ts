import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Routes } from '@angular/router';
import {UserComponent } from "./views/user/user.component"

const appRoutes: Routes = [
  { path: 'user', component: UserComponent },
  { path: '', redirectTo: '/user', pathMatch: 'full' },
];

@NgModule({
  imports: [
    RouterModule.forRoot(
      appRoutes,
      {
        enableTracing: true, // <-- debugging purposes only
      }),
  ],
  exports: [
    RouterModule
  ],
})
export class AppRoutingModule { }
