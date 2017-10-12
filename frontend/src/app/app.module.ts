import { BrowserModule } from '@angular/platform-browser';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpModule } from '@angular/http';
import { UserService} from "./user/user.service";
import { AppComponent } from './app.component';
import { GoogleApiModule, NG_GAPI_CONFIG, ClientConfig} from "ng-gapi";
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import {
  MatButtonModule, MatCardModule, MatMenuModule, MatToolbarModule, MatIconModule,
  MatInputModule, MatTooltipModule, MatProgressSpinnerModule,
} from '@angular/material';
import { NgLoggerModule, Level } from '@nsalaun/ng-logger';
import { ApolloClient, createNetworkInterface } from 'apollo-client';
import { ApolloModule } from 'apollo-angular';
import {isNull, isUndefined} from "util";
import { UserComponent } from './views/user/user.component';
import {AppRoutingModule} from "./app-routing.module";
import { ReactiveFormsModule } from '@angular/forms';
import { environment } from '../environments/environment';

const networkInterface = createNetworkInterface('/graphql');

networkInterface.use([{
  applyMiddleware(req, next) {
    if (!req.options.headers) {
      req.options.headers = {};  // Create the header object if needed.
    }
    // get the authentication token from local storage if it exists
    let token = sessionStorage.getItem("access_token");
    if (!isNull(token)){
       req.options.headers.authorization = sessionStorage.getItem('gid') + ":" + token
      //req.options.headers.authorization = token
    }
    next();
  }
}]);


const client = new ApolloClient({
  networkInterface,
});

export function provideClient(): ApolloClient {
  return client;
}

let gapiClientConfig: ClientConfig = {
  clientId: environment.googleClientId,
  discoveryDocs: ["https://www.googleapis.com/discovery/v1/apis/drive/v3/rest"],
  scope: environment.scope.join(" ")
};


@NgModule({
  declarations: [
    AppComponent,
    UserComponent,
  ],
  imports: [
    NgLoggerModule.forRoot(Level.DEBUG),
    AppRoutingModule,
    BrowserModule,
    FormsModule,
    ReactiveFormsModule,
    HttpModule,
    BrowserAnimationsModule,
    MatButtonModule,
    MatMenuModule,
    MatCardModule,
    MatInputModule,
    MatTooltipModule,
    MatToolbarModule,
    MatIconModule,
    MatProgressSpinnerModule,
    ApolloModule.forRoot(provideClient),
    GoogleApiModule.forRoot({
      provide: NG_GAPI_CONFIG,
      useValue: gapiClientConfig,
})
  ],
  providers: [
    UserService,
  ],
  bootstrap: [AppComponent]
})
export class AppModule { }
