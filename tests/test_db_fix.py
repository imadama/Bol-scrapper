import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'bol_scraper')))

# Mock env
with patch.dict(os.environ, {
    'DATABASE_URL': 'sqlite:///:memory:',
    'FLASK_SECRET_KEY': 'test-secret',
    'HEADLESS': 'true'
}):
    from app import app, init_db, get_db_session, User, Product, Base, engine

class TestDatabaseFix(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app = app.test_client()
        
        # Setup DB (clean state)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        # Create test user
        self.db = get_db_session()
        self.user = User(username='testuser', password_hash='hash')
        self.db.add(self.user)
        self.db.commit()
        self.user_id = self.user.id
        self.db.close()

    def tearDown(self):
        pass

    @patch('app.scrape_bol_product')
    @patch('app.process_images_into_static')
    def test_bol_scrape_id_capture(self, mock_images, mock_scrape):
        """Test bol_scrape for DetachedInstanceError."""
        mock_scrape.return_value = {
            'title': 'Test Product',
            'main_image': 'http://example.com/img.jpg',
            'all_images': '',
            'price_value': 10.0,
            'list_price_value': 20.0
        }
        mock_images.return_value = ('/static/main.jpg', '/static/all.jpg')

        with self.app.session_transaction() as sess:
            sess['user_id'] = self.user_id

        response = self.app.post('/bol/scrape', data={'url': 'https://www.bol.com/nl/p/test/12345/'}, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Bewerk Productdata', response.data)
        
        db = get_db_session()
        product = db.query(Product).filter_by(title='Test Product').first()
        self.assertIsNotNone(product)
        self.assertEqual(product.user_id, self.user_id)
        db.close()

    @patch('app.scrape_printables_product')
    @patch('app.process_images_into_static')
    def test_printables_scrape_id_capture(self, mock_images, mock_scrape):
        """Test printables_scrape for DetachedInstanceError."""
        mock_scrape.return_value = {
            'title': 'Test Printable',
            'main_image': 'http://example.com/p.jpg',
            'all_images': '',
        }
        mock_images.return_value = ('/static/p_main.jpg', '')

        with self.app.session_transaction() as sess:
            sess['user_id'] = self.user_id

        response = self.app.post('/printables/scrape', data={'url': 'https://www.printables.com/model/123'}, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Bewerk Productdata', response.data)

if __name__ == '__main__':
    unittest.main()
