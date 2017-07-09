import { AngulardemoPage } from './app.po';

describe('angulardemo App', () => {
  let page: AngulardemoPage;

  beforeEach(() => {
    page = new AngulardemoPage();
  });

  it('should display message saying app works', () => {
    page.navigateTo();
    expect(page.getParagraphText()).toEqual('app works!');
  });
});
