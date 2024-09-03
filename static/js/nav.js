function getApp() {

    const path = window.location.pathname;

    const pathArray = path.split('/');

    let app = pathArray[1];

    if (app === '') {
        app = 'agenda';
    }

    return app;
}


function highlightNavLink() {

    const mainNav = document.querySelector('#nav-main');
    const navLinks = mainNav.querySelectorAll('.nav-link');

    let link;
    for (link of navLinks) {

        if (link.id === 'nav-' + getApp()) {

            link.classList.add('active');

        }

    }

}


highlightNavLink();
